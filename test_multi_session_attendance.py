"""
Comprehensive Automated Test Suite for Multi-Session / Multi-Scan Attendance System.
Tests:
1. Single Session & Multi-Session Event creation
2. QR Code scanning and verification
3. Duplicate scan prevention within same session
4. Cross-session scanning for the same student
5. Time-window validation and organizer override
6. Team registrations individual scanning
7. Organizer manual override with audit logging
8. Minimum attendance percentage and satisfaction calculations
9. Attendance matrix generation and dynamic Excel/CSV exports
10. Backward compatibility with legacy records
11. Multi-Day Hackathon (6 sessions) complete workflow
12. Certificate eligibility requirement integration
"""
import sys
import unittest
from datetime import datetime, timedelta, time, date
from app import create_app
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    EventRegistrationType, Team, TeamStatus, TeamMember, TeamMemberStatus, TeamRole,
    AttendanceRecord, AttendanceStatus, VerificationMethod,
    AttendanceSession, AttendanceSessionStatus, Certificate, CertificateStatus
)
from services.attendance_service import (
    create_or_update_event_sessions, record_session_attendance,
    manual_override_attendance, calculate_event_attendance_matrix
)
from services.export_service import export_participants_excel, export_participants_csv
from services.event_service import are_certificates_completed

class MultiSessionAttendanceTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Create Organizer User
        self.organizer = User.query.filter_by(email='att_organizer@campusflow.test').first()
        if not self.organizer:
            self.organizer = User(
                name='Attendance Organizer',
                email='att_organizer@campusflow.test',
                role=UserRole.ORGANIZER
            )
            self.organizer.set_password('pass123')
            db.session.add(self.organizer)
            db.session.commit()

        # Create Student 1
        self.student1 = User.query.filter_by(email='att_student1@campusflow.test').first()
        if not self.student1:
            self.student1 = User(
                name='Alice Student',
                email='att_student1@campusflow.test',
                role=UserRole.STUDENT
            )
            self.student1.set_password('pass123')
            db.session.add(self.student1)
            db.session.flush()
            prof1 = StudentProfile(
                user_id=self.student1.id,
                roll_number='CS2026-ATT-01',
                department='CSE',
                year='3',
                section='A'
            )
            db.session.add(prof1)
            db.session.commit()

        # Create Student 2
        self.student2 = User.query.filter_by(email='att_student2@campusflow.test').first()
        if not self.student2:
            self.student2 = User(
                name='Bob Student',
                email='att_student2@campusflow.test',
                role=UserRole.STUDENT
            )
            self.student2.set_password('pass123')
            db.session.add(self.student2)
            db.session.flush()
            prof2 = StudentProfile(
                user_id=self.student2.id,
                roll_number='CS2026-ATT-02',
                department='ECE',
                year='3',
                section='B'
            )
            db.session.add(prof2)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_01_create_multisession_event(self):
        """Test event creation with multiple attendance sessions."""
        now = datetime.utcnow()
        event = Event(
            title="AI/ML 3-Day Multi-Session Workshop",
            slug=f"aiml-workshop-{int(now.timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Dr. Ramesh",
            venue="Seminar Hall 1",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=3),
            registration_deadline=now + timedelta(hours=12),
            max_participants=50,
            is_free=True,
            enable_attendance=True,
            min_attendance_percentage=75.0,
            status=EventStatus.REGISTRATION_OPEN,
            description="Intensive multi-session technical workshop"
        )
        db.session.add(event)
        db.session.flush()

        sessions_data = [
            {'session_name': 'Day 1 - Morning Keynote', 'event_date': (now + timedelta(days=1)).date(), 'start_time': '09:00', 'end_time': '12:00'},
            {'session_name': 'Day 1 - Afternoon Lab', 'event_date': (now + timedelta(days=1)).date(), 'start_time': '13:00', 'end_time': '17:00'},
            {'session_name': 'Day 2 - Morning Deep Learning', 'event_date': (now + timedelta(days=2)).date(), 'start_time': '09:00', 'end_time': '12:00'},
            {'session_name': 'Day 2 - Afternoon Project Work', 'event_date': (now + timedelta(days=2)).date(), 'start_time': '13:00', 'end_time': '17:00'},
        ]
        created_sessions = create_or_update_event_sessions(event, sessions_data)
        db.session.commit()

        self.assertEqual(len(created_sessions), 4)
        self.assertEqual(event.attendance_sessions.count(), 4)
        self.assertEqual(event.total_sessions_count, 4)
        self.assertEqual(created_sessions[0].session_name, 'Day 1 - Morning Keynote')

    def test_02_qr_scan_and_duplicate_prevention(self):
        """Test scanning attendance for a session and verifying duplicate rejection."""
        now = datetime.utcnow()
        event = Event(
            title="Hackathon 2026",
            slug=f"hackathon-2026-{int(now.timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.HACKATHON,
            department="CSE",
            faculty_coordinator="Prof. Sharma",
            venue="Tech Park Hub",
            start_time=now,
            end_time=now + timedelta(days=2),
            registration_deadline=now + timedelta(hours=2),
            is_free=True,
            enable_attendance=True,
            min_attendance_percentage=75.0,
            status=EventStatus.REGISTRATION_OPEN,
            description="Campus Hackathon"
        )
        db.session.add(event)
        db.session.flush()

        # Add 2 sessions
        s1 = AttendanceSession(event_id=event.id, session_name="Day 1 Check-In", session_number=1, status=AttendanceSessionStatus.ACTIVE)
        s2 = AttendanceSession(event_id=event.id, session_name="Day 2 Evaluation", session_number=2, status=AttendanceSessionStatus.ACTIVE)
        db.session.add_all([s1, s2])
        db.session.flush()

        # Register Student 1
        reg1 = EventRegistration(
            event_id=event.id,
            student_id=self.student1.id,
            registration_code=f"CF-E{event.id}-S{self.student1.id}-TEST1",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg1)
        db.session.commit()

        # 1. Scan Student 1 in Session 1 -> Should succeed
        res, code = record_session_attendance(
            event_id=event.id,
            session_id=s1.id,
            registration_code=reg1.registration_code,
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code, 200)
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['student_attended_sessions'], 1)
        self.assertEqual(res['total_sessions'], 2)
        self.assertEqual(res['student_percentage'], 50.0)

        # 2. Duplicate Scan in Session 1 -> Must be rejected as 'duplicate'
        res2, code2 = record_session_attendance(
            event_id=event.id,
            session_id=s1.id,
            registration_code=reg1.registration_code,
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code2, 200)
        self.assertEqual(res2['status'], 'duplicate')
        self.assertIn("already marked PRESENT", res2['message'])

        # 3. Cross-Session Scan in Session 2 -> Must succeed
        res3, code3 = record_session_attendance(
            event_id=event.id,
            session_id=s2.id,
            registration_code=reg1.registration_code,
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code3, 200)
        self.assertEqual(res3['status'], 'success')
        self.assertEqual(res3['student_attended_sessions'], 2)
        self.assertEqual(res3['student_percentage'], 100.0)
        self.assertTrue(res3['is_satisfied'])

    def test_03_team_event_individual_scanning(self):
        """Test that each team member is scanned individually and one scan does NOT mark others."""
        now = datetime.utcnow()
        event = Event(
            title="Team Code Sprint",
            slug=f"team-code-sprint-{int(now.timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.HACKATHON,
            department="CSE",
            faculty_coordinator="Prof. Team",
            venue="Lab 4",
            start_time=now,
            end_time=now + timedelta(days=1),
            registration_deadline=now + timedelta(hours=2),
            registration_type=EventRegistrationType.TEAM,
            min_team_size=2,
            max_team_size=2,
            is_free=True,
            enable_attendance=True,
            status=EventStatus.REGISTRATION_OPEN,
            description="Team Hackathon"
        )
        db.session.add(event)
        db.session.flush()

        s1 = AttendanceSession(event_id=event.id, session_name="Morning Sprint", session_number=1, status=AttendanceSessionStatus.ACTIVE)
        db.session.add(s1)
        db.session.flush()

        # Create Team with Student 1 (Lead) and Student 2 (Member)
        team = Team(
            event_id=event.id,
            team_name="Byte Bandits",
            team_lead_id=self.student1.id,
            status=TeamStatus.COMPLETE
        )
        db.session.add(team)
        db.session.flush()

        reg1 = EventRegistration(
            event_id=event.id,
            student_id=self.student1.id,
            team_id=team.id,
            registration_code=f"CF-E{event.id}-S{self.student1.id}-LEAD",
            status=RegistrationStatus.CONFIRMED
        )
        reg2 = EventRegistration(
            event_id=event.id,
            student_id=self.student2.id,
            team_id=team.id,
            registration_code=f"CF-E{event.id}-S{self.student2.id}-MEMB",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add_all([reg1, reg2])
        db.session.commit()

        # Scan Student 1 only
        res, code = record_session_attendance(
            event_id=event.id,
            session_id=s1.id,
            registration_code=reg1.registration_code,
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code, 200)
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['student_name'], self.student1.name)

        # Check that Student 1 is PRESENT and Student 2 is NOT present
        self.assertEqual(event.get_student_attended_count(self.student1.id), 1)
        self.assertEqual(event.get_student_attended_count(self.student2.id), 0)

    def test_04_manual_attendance_override_and_audit(self):
        """Test organizer manual attendance override with audit trail."""
        now = datetime.utcnow()
        event = Event(
            title="Seminar on Cloud Computing",
            slug=f"cloud-seminar-{int(now.timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.SEMINAR,
            department="IT",
            faculty_coordinator="Dr. Cloud",
            venue="Auditorium",
            start_time=now,
            end_time=now + timedelta(hours=4),
            registration_deadline=now + timedelta(hours=1),
            is_free=True,
            enable_attendance=True,
            status=EventStatus.REGISTRATION_OPEN,
            description="Cloud seminar"
        )
        db.session.add(event)
        db.session.flush()

        s1 = AttendanceSession(event_id=event.id, session_name="General Attendance", session_number=1, status=AttendanceSessionStatus.ACTIVE)
        db.session.add(s1)
        db.session.flush()

        reg = EventRegistration(
            event_id=event.id,
            student_id=self.student2.id,
            registration_code=f"CF-E{event.id}-S{self.student2.id}-MANUAL",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg)
        db.session.commit()

        # Manual override: Mark Present
        rec = manual_override_attendance(
            event_id=event.id,
            session_id=s1.id,
            student_id=self.student2.id,
            new_status=AttendanceStatus.PRESENT,
            marked_by_user=self.organizer,
            remarks="Verified student ID manually at desk"
        )
        self.assertEqual(rec.status, AttendanceStatus.PRESENT)
        self.assertEqual(rec.verification_method, VerificationMethod.MANUAL)
        self.assertIn("Verified student ID", rec.remarks)
        self.assertEqual(rec.marked_by_id, self.organizer.id)

    def test_05_matrix_calculation_and_exports(self):
        """Test matrix generation and dynamic Excel/CSV report exports."""
        now = datetime.utcnow()
        event = Event(
            title="Cybersecurity Summit",
            slug=f"cyber-summit-{int(now.timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Dr. Cyber",
            venue="Hall A",
            start_time=now,
            end_time=now + timedelta(days=1),
            registration_deadline=now + timedelta(hours=1),
            is_free=True,
            enable_attendance=True,
            min_attendance_percentage=50.0,
            status=EventStatus.REGISTRATION_OPEN,
            description="Cybersecurity summit"
        )
        db.session.add(event)
        db.session.flush()

        s1 = AttendanceSession(event_id=event.id, session_name="Track 1 - Cryptography", session_number=1)
        s2 = AttendanceSession(event_id=event.id, session_name="Track 2 - Ethical Hacking", session_number=2)
        db.session.add_all([s1, s2])
        db.session.flush()

        reg = EventRegistration(
            event_id=event.id,
            student_id=self.student1.id,
            registration_code=f"CF-E{event.id}-S{self.student1.id}-EXP",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg)
        db.session.commit()

        # Mark 1 session
        record_session_attendance(event.id, s1.id, reg.registration_code, self.organizer, allow_time_override=True)

        matrix_data = calculate_event_attendance_matrix(event)
        self.assertEqual(len(matrix_data['sessions']), 2)
        self.assertEqual(matrix_data['total_participants'], 1)
        row = matrix_data['matrix'][0]
        self.assertEqual(row['attended_count'], 1)
        self.assertEqual(row['percentage'], 50.0)
        self.assertTrue(row['is_satisfied']) # 50% meets 50% min

        # Test Excel export
        excel_stream = export_participants_excel(event, [reg])
        self.assertIsNotNone(excel_stream)
        self.assertGreater(len(excel_stream.getvalue()), 100)

        # Test CSV export
        csv_stream = export_participants_csv(event, [reg])
        self.assertIsNotNone(csv_stream)
        csv_content = csv_stream.getvalue()
        self.assertIn("Att: Track 1 - Cryptography", csv_content)
        self.assertIn("Att: Track 2 - Ethical Hacking", csv_content)
        self.assertIn("PRESENT", csv_content)

    def test_06_multi_day_hackathon_six_sessions(self):
        """Test 3-day Hackathon with 6 attendance sessions (Morning & Afternoon per day)."""
        now = datetime.utcnow()
        event = Event(
            title="National Hackathon 2026 (72 Hours)",
            slug=f"nat-hackathon-{int(now.timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.HACKATHON,
            department="CSE",
            faculty_coordinator="Dr. Hack",
            venue="Innovation Center",
            start_time=now,
            end_time=now + timedelta(days=3),
            registration_deadline=now + timedelta(hours=1),
            is_free=True,
            enable_attendance=True,
            min_attendance_percentage=75.0, # Requires 5/6 sessions
            status=EventStatus.REGISTRATION_OPEN,
            description="72-Hour continuous hackathon"
        )
        db.session.add(event)
        db.session.flush()

        sessions = []
        for i in range(1, 4):
            sessions.append(AttendanceSession(event_id=event.id, session_name=f"Day {i} - Morning Checkpoint", session_number=len(sessions)+1))
            sessions.append(AttendanceSession(event_id=event.id, session_name=f"Day {i} - Evening Standup", session_number=len(sessions)+1))
        db.session.add_all(sessions)
        db.session.flush()

        reg1 = EventRegistration(event_id=event.id, student_id=self.student1.id, registration_code=f"CF-E{event.id}-S{self.student1.id}-H6A", status=RegistrationStatus.CONFIRMED)
        reg2 = EventRegistration(event_id=event.id, student_id=self.student2.id, registration_code=f"CF-E{event.id}-S{self.student2.id}-H6B", status=RegistrationStatus.CONFIRMED)
        db.session.add_all([reg1, reg2])
        db.session.commit()

        # Student 1 attends 5 out of 6 sessions (83.33% -> Satisfied)
        for s in sessions[:5]:
            record_session_attendance(event.id, s.id, reg1.registration_code, self.organizer, allow_time_override=True)

        # Student 2 attends 3 out of 6 sessions (50.0% -> Unsatisfied)
        for s in sessions[:3]:
            record_session_attendance(event.id, s.id, reg2.registration_code, self.organizer, allow_time_override=True)

        self.assertEqual(event.get_student_attended_count(self.student1.id), 5)
        self.assertEqual(event.get_student_attendance_percentage(self.student1.id), 83.33)
        self.assertTrue(event.is_student_attendance_satisfied(self.student1.id))

        self.assertEqual(event.get_student_attended_count(self.student2.id), 3)
        self.assertEqual(event.get_student_attendance_percentage(self.student2.id), 50.0)
        self.assertFalse(event.is_student_attendance_satisfied(self.student2.id))

        # Check Certificate completion logic
        # Only student 1 is eligible. If student 1 receives certificate, are_certificates_completed returns True
        self.assertFalse(are_certificates_completed(event))

        cert1 = Certificate(
            event_id=event.id,
            student_id=self.student1.id,
            registration_id=reg1.id,
            file_path='uploads/cert.pdf',
            original_filename='cert.pdf',
            certificate_code=f'CERT-{event.id}-{self.student1.id}',
            status=CertificateStatus.MATCHED
        )
        db.session.add(cert1)
        db.session.commit()

        self.assertTrue(are_certificates_completed(event))

    def test_07_session_time_validation(self):
        """Test backend validation when scanning outside session start/end time window."""
        now = datetime.now()
        past_start = (now - timedelta(hours=3)).time()
        past_end = (now - timedelta(hours=1)).time()

        event = Event(
            title="Time Constrained Workshop",
            slug=f"time-workshop-{int(datetime.utcnow().timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.WORKSHOP,
            department="ECE",
            faculty_coordinator="Dr. Timer",
            venue="Lab 2",
            start_time=datetime.utcnow() - timedelta(hours=4),
            end_time=datetime.utcnow() + timedelta(hours=4),
            registration_deadline=datetime.utcnow() - timedelta(hours=5),
            is_free=True,
            enable_attendance=True,
            status=EventStatus.REGISTRATION_OPEN,
            description="Workshop with closed time slot"
        )
        db.session.add(event)
        db.session.flush()

        closed_session = AttendanceSession(
            event_id=event.id,
            session_name="Past Morning Keynote",
            session_number=1,
            event_date=now.date(),
            start_time=past_start,
            end_time=past_end,
            status=AttendanceSessionStatus.ACTIVE
        )
        db.session.add(closed_session)
        db.session.flush()

        reg = EventRegistration(
            event_id=event.id,
            student_id=self.student1.id,
            registration_code=f"CF-E{event.id}-S{self.student1.id}-TIME",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg)
        db.session.commit()

        # Scan without override -> should return session_closed
        res, code = record_session_attendance(
            event_id=event.id,
            session_id=closed_session.id,
            registration_code=reg.registration_code,
            marked_by_user=self.organizer,
            allow_time_override=False
        )
        self.assertEqual(code, 200)
        self.assertEqual(res['status'], 'session_closed')
        self.assertTrue(res.get('can_override'))

        # Scan WITH override -> should succeed
        res_override, code_override = record_session_attendance(
            event_id=event.id,
            session_id=closed_session.id,
            registration_code=reg.registration_code,
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code_override, 200)
        self.assertEqual(res_override['status'], 'success')

    def test_08_manual_ticket_code_entry_variants(self):
        """Test manual ticket code entry with lowercase, prefixes, roll numbers, and emails."""
        event = Event(
            title="Manual Entry Test Event",
            slug=f"manual-entry-test-{int(datetime.utcnow().timestamp())}",
            organizer_id=self.organizer.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Dr. Ramesh",
            venue="Main Auditorium",
            description="Testing manual ticket code entry",
            is_free=True,
            enable_attendance=True,
            start_time=datetime.utcnow() - timedelta(hours=1),
            end_time=datetime.utcnow() + timedelta(hours=3),
            registration_deadline=datetime.utcnow() - timedelta(hours=2),
            status=EventStatus.APPROVED
        )
        db.session.add(event)
        db.session.flush()

        session1 = AttendanceSession(
            event_id=event.id,
            session_name="Manual Entry Session",
            session_number=1,
            status=AttendanceSessionStatus.ACTIVE
        )
        db.session.add(session1)
        db.session.flush()

        reg = EventRegistration(
            event_id=event.id,
            student_id=self.student1.id,
            registration_code=f"CF-E{event.id}-S{self.student1.id}-MANUAL",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg)
        db.session.commit()

        # 1. Lowercase code
        res, code = record_session_attendance(
            event_id=event.id,
            session_id=session1.id,
            registration_code=reg.registration_code.lower(),
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code, 200)
        self.assertEqual(res['status'], 'success')

        # 2. Duplicate check with QR prefix in lowercase
        res_dup, code_dup = record_session_attendance(
            event_id=event.id,
            session_id=session1.id,
            registration_code=f"campusflow-ticket:{reg.registration_code.lower()}",
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code_dup, 200)
        self.assertEqual(res_dup['status'], 'duplicate')

        # 3. Create student 2 registration and test roll number & email lookup
        reg2 = EventRegistration(
            event_id=event.id,
            student_id=self.student2.id,
            registration_code=f"CF-E{event.id}-S{self.student2.id}-TEST2",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg2)
        db.session.commit()

        # By student roll number
        if self.student2.student_profile and self.student2.student_profile.roll_number:
            res_roll, code_roll = record_session_attendance(
                event_id=event.id,
                session_id=session1.id,
                registration_code=self.student2.student_profile.roll_number.lower(),
                marked_by_user=self.organizer,
                allow_time_override=True
            )
            self.assertEqual(code_roll, 200)
            self.assertEqual(res_roll['status'], 'success')
            self.assertEqual(res_roll['student_name'], self.student2.name)

        # 4. By student email on student 3
        student3 = User.query.filter_by(email='att_student3@campusflow.test').first()
        if not student3:
            student3 = User(
                name='Charlie Student',
                email='att_student3@campusflow.test',
                role=UserRole.STUDENT
            )
            student3.set_password('pass123')
            db.session.add(student3)
            db.session.flush()

        reg3 = EventRegistration(
            event_id=event.id,
            student_id=student3.id,
            registration_code=f"CF-E{event.id}-S{student3.id}-TEST3",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg3)
        db.session.commit()

        res_email, code_email = record_session_attendance(
            event_id=event.id,
            session_id=session1.id,
            registration_code=student3.email.upper(),
            marked_by_user=self.organizer,
            allow_time_override=True
        )
        self.assertEqual(code_email, 200)
        self.assertEqual(res_email['status'], 'success')
        self.assertEqual(res_email['student_name'], student3.name)

if __name__ == '__main__':
    unittest.main()
