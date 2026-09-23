import os
import unittest
import json
import uuid
from datetime import datetime, timedelta
from app import create_app
from config import Config
from models import (
    db, User, UserRole, StudentProfile, CollegeDepartment, Event,
    EventRegistration, RegistrationStatus, AttendanceRecord, AttendanceStatus,
    AttendanceSession, EventStatus, VerificationMethod
)
from services.attendance_service import get_registered_not_attended_students


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


class TestHODRegisteredNotAttended(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create CSM HOD
        self.hod_csm = User(
            name="Dr. HOD CSM",
            email="hod.csm@campusflow.edu",
            role=UserRole.HOD,
            is_active=True
        )
        self.hod_csm.set_password("password123")

        # Create CSE HOD
        self.hod_cse = User(
            name="Dr. HOD CSE",
            email="hod.cse@campusflow.edu",
            role=UserRole.HOD,
            is_active=True
        )
        self.hod_cse.set_password("password123")

        # Create Organizer
        self.organizer = User(
            name="Event Organizer",
            email="org@campusflow.edu",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        self.organizer.set_password("password123")

        # Create Students
        self.student_csm_absent = User(name="Rahul Kumar", email="rahul@csm.edu", role=UserRole.STUDENT, is_active=True)
        self.student_csm_absent.set_password("password123")

        self.student_csm_present = User(name="Priya Sharma", email="priya@csm.edu", role=UserRole.STUDENT, is_active=True)
        self.student_csm_present.set_password("password123")

        self.student_cse_absent = User(name="Amit Patel", email="amit@cse.edu", role=UserRole.STUDENT, is_active=True)
        self.student_cse_absent.set_password("password123")

        self.student_csm_cancelled = User(name="Vikram Singh", email="vikram@csm.edu", role=UserRole.STUDENT, is_active=True)
        self.student_csm_cancelled.set_password("password123")

        db.session.add_all([
            self.hod_csm, self.hod_cse, self.organizer,
            self.student_csm_absent, self.student_csm_present,
            self.student_cse_absent, self.student_csm_cancelled
        ])
        db.session.commit()

        # Create Departments and assign HODs
        self.dept_csm = CollegeDepartment(
            name="Computer Science & Machine Learning",
            code="CSM",
            is_active=True,
            hod_id=self.hod_csm.id
        )
        self.dept_cse = CollegeDepartment(
            name="Computer Science & Engineering",
            code="CSE",
            is_active=True,
            hod_id=self.hod_cse.id
        )
        db.session.add_all([self.dept_csm, self.dept_cse])
        db.session.commit()

        # Profiles
        self.prof_csm_absent = StudentProfile(
            user_id=self.student_csm_absent.id,
            roll_number="25881A6601",
            department="CSM",
            year=3,
            section="A"
        )
        self.prof_csm_present = StudentProfile(
            user_id=self.student_csm_present.id,
            roll_number="25881A6602",
            department="CSM",
            year=3,
            section="A"
        )
        self.prof_cse_absent = StudentProfile(
            user_id=self.student_cse_absent.id,
            roll_number="25881A0501",
            department="CSE",
            year=3,
            section="A"
        )
        self.prof_csm_cancelled = StudentProfile(
            user_id=self.student_csm_cancelled.id,
            roll_number="25881A6603",
            department="CSM",
            year=3,
            section="A"
        )
        db.session.add_all([
            self.prof_csm_absent, self.prof_csm_present,
            self.prof_cse_absent, self.prof_csm_cancelled
        ])
        db.session.commit()

        # Events
        # Event 1: Completed event (started yesterday, completed)
        yesterday = datetime.utcnow() - timedelta(days=1)
        self.event_completed = Event(
            title="Python Workshop",
            slug="python-workshop-test",
            organizer_id=self.organizer.id,
            department_id=self.dept_csm.id,
            department="CSM",
            venue="Lab 1",
            description="Python hands-on session",
            faculty_coordinator="Prof. Sharma",
            registration_deadline=yesterday - timedelta(hours=2),
            start_time=yesterday,
            end_time=yesterday + timedelta(hours=3),
            status=EventStatus.COMPLETED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            enable_attendance=True,
            max_participants=100
        )

        # Event 2: Future event (starts tomorrow)
        tomorrow = datetime.utcnow() + timedelta(days=1)
        self.event_future = Event(
            title="AI Hackathon Future",
            slug="ai-hackathon-future-test",
            organizer_id=self.organizer.id,
            department_id=self.dept_csm.id,
            department="CSM",
            venue="Main Hall",
            description="Future AI Hackathon",
            faculty_coordinator="Prof. Rao",
            registration_deadline=tomorrow - timedelta(hours=2),
            start_time=tomorrow,
            end_time=tomorrow + timedelta(hours=5),
            status=EventStatus.UPCOMING,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            enable_attendance=True,
            max_participants=50
        )

        # Event 3: Multi-session event (completed)
        self.event_multi = Event(
            title="Deep Learning Bootcamp",
            slug="deep-learning-bootcamp-test",
            organizer_id=self.organizer.id,
            department_id=self.dept_csm.id,
            department="CSM",
            venue="Auditorium",
            description="2-day bootcamp",
            faculty_coordinator="Prof. Reddy",
            registration_deadline=yesterday - timedelta(days=2),
            start_time=yesterday - timedelta(days=1),
            end_time=yesterday,
            status=EventStatus.COMPLETED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            enable_attendance=True,
            min_attendance_percentage=100.0,
            max_participants=60
        )

        db.session.add_all([self.event_completed, self.event_future, self.event_multi])
        db.session.commit()

        # Add sessions for multi-session event
        self.session1 = AttendanceSession(
            event_id=self.event_multi.id,
            session_name="Day 1",
            session_number=1,
            event_date=yesterday.date() - timedelta(days=1),
            status="COMPLETED"
        )
        self.session2 = AttendanceSession(
            event_id=self.event_multi.id,
            session_name="Day 2",
            session_number=2,
            event_date=yesterday.date(),
            status="COMPLETED"
        )
        db.session.add_all([self.session1, self.session2])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_department_isolation_and_absent_detection(self):
        """Test that CSM HOD only sees CSM absentees, and CSE HOD only sees CSE absentees."""
        # Rahul (CSM) registers for completed event -> CONFIRMED, no attendance
        reg_rahul = EventRegistration(
            event_id=self.event_completed.id,
            student_id=self.student_csm_absent.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        # Priya (CSM) registers for completed event -> CONFIRMED, attended
        reg_priya = EventRegistration(
            event_id=self.event_completed.id,
            student_id=self.student_csm_present.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        # Amit (CSE) registers for completed event -> CONFIRMED, no attendance
        reg_amit = EventRegistration(
            event_id=self.event_completed.id,
            student_id=self.student_cse_absent.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add_all([reg_rahul, reg_priya, reg_amit])
        db.session.commit()

        # Priya attends
        rec_priya = AttendanceRecord(
            registration_id=reg_priya.id,
            event_id=self.event_completed.id,
            student_id=self.student_csm_present.id,
            status=AttendanceStatus.PRESENT,
            verification_method=VerificationMethod.QR_SCAN
        )
        db.session.add(rec_priya)
        db.session.commit()

        # 1. Query for CSM HOD
        csm_res = get_registered_not_attended_students(self.hod_csm)
        records = csm_res['records']

        # Rahul should be present in CSM absentees
        rahul_records = [r for r in records if r['student_id'] == self.student_csm_absent.id]
        self.assertEqual(len(rahul_records), 1)
        self.assertEqual(rahul_records[0]['roll_number'], "25881A6601")
        self.assertEqual(rahul_records[0]['department'], "CSM")
        self.assertEqual(rahul_records[0]['attendance_status'], "Not Attended")
        self.assertEqual(rahul_records[0]['registration_status'], RegistrationStatus.CONFIRMED)

        # Priya attended -> MUST NOT be in absentee list
        priya_records = [r for r in records if r['student_id'] == self.student_csm_present.id]
        self.assertEqual(len(priya_records), 0)

        # Amit is CSE -> MUST NOT be in CSM absentee list (Strict isolation!)
        amit_records = [r for r in records if r['student_id'] == self.student_cse_absent.id]
        self.assertEqual(len(amit_records), 0)

        # 2. Query for CSE HOD
        cse_res = get_registered_not_attended_students(self.hod_cse)
        cse_records = cse_res['records']

        # Amit (CSE) MUST be in CSE absentees
        amit_cse = [r for r in cse_records if r['student_id'] == self.student_cse_absent.id]
        self.assertEqual(len(amit_cse), 1)
        self.assertEqual(amit_cse[0]['department'], "CSE")

        # Rahul (CSM) MUST NOT be in CSE absentees
        rahul_cse = [r for r in cse_records if r['student_id'] == self.student_csm_absent.id]
        self.assertEqual(len(rahul_cse), 0)

    def test_future_event_excluded(self):
        """Events that have not started must NOT show registered students as absent."""
        reg_future = EventRegistration(
            event_id=self.event_future.id,
            student_id=self.student_csm_absent.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg_future)
        db.session.commit()

        csm_res = get_registered_not_attended_students(self.hod_csm, event_id=self.event_future.id)
        self.assertEqual(csm_res['total'], 0)
        self.assertEqual(len(csm_res['records']), 0)

    def test_cancelled_registration_excluded(self):
        """Cancelled registrations must NOT show in absentee list."""
        reg_cancelled = EventRegistration(
            event_id=self.event_completed.id,
            student_id=self.student_csm_cancelled.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CANCELLED
        )
        db.session.add(reg_cancelled)
        db.session.commit()

        csm_res = get_registered_not_attended_students(self.hod_csm, event_id=self.event_completed.id)
        vikram_records = [r for r in csm_res['records'] if r['student_id'] == self.student_csm_cancelled.id]
        self.assertEqual(len(vikram_records), 0)

    def test_multi_session_satisfaction(self):
        """Multi-session events: students who fail required attendance criteria should be flagged as absent."""
        reg_multi = EventRegistration(
            event_id=self.event_multi.id,
            student_id=self.student_csm_absent.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg_multi)
        db.session.commit()

        # Attend session 1 only (50% < 100% required)
        rec1 = AttendanceRecord(
            registration_id=reg_multi.id,
            event_id=self.event_multi.id,
            session_id=self.session1.id,
            student_id=self.student_csm_absent.id,
            status=AttendanceStatus.PRESENT
        )
        db.session.add(rec1)
        db.session.commit()

        csm_res = get_registered_not_attended_students(self.hod_csm, event_id=self.event_multi.id)
        self.assertEqual(csm_res['total'], 1)
        rec = csm_res['records'][0]
        self.assertEqual(rec['student_id'], self.student_csm_absent.id)
        self.assertTrue(rec['multi_session'])
        self.assertEqual(rec['attended_sessions'], 1)
        self.assertEqual(rec['total_sessions'], 2)

    def test_filters_and_search(self):
        """Test filtering by event, date, and searching student name/roll number."""
        reg1 = EventRegistration(
            event_id=self.event_completed.id,
            student_id=self.student_csm_absent.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg1)
        db.session.commit()

        # Search by roll number
        res_search_roll = get_registered_not_attended_students(self.hod_csm, search="25881A6601")
        self.assertEqual(res_search_roll['total'], 1)

        # Search by wrong roll number
        res_search_none = get_registered_not_attended_students(self.hod_csm, search="999999999")
        self.assertEqual(res_search_none['total'], 0)

        # Search by student name
        res_search_name = get_registered_not_attended_students(self.hod_csm, search="Rahul")
        self.assertEqual(res_search_name['total'], 1)

        # Filter by event_id
        res_event = get_registered_not_attended_students(self.hod_csm, event_id=self.event_completed.id)
        self.assertEqual(res_event['total'], 1)

        # Filter by non-existent event
        res_event_none = get_registered_not_attended_students(self.hod_csm, event_id=99999)
        self.assertEqual(res_event_none['total'], 0)

    def test_api_endpoint(self):
        """Test /hod/registered-not-attended and /api/hod/registered-not-attended endpoints."""
        reg1 = EventRegistration(
            event_id=self.event_completed.id,
            student_id=self.student_csm_absent.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg1)
        db.session.commit()

        client = self.app.test_client()

        # Without login -> redirected to login
        res = client.get('/hod/registered-not-attended')
        self.assertIn(res.status_code, [302, 401])

        # Login as CSM HOD
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.hod_csm.id)
            sess['user_id'] = self.hod_csm.id
            sess['role'] = 'HOD'

        # Test GET /hod/registered-not-attended
        res = client.get('/hod/registered-not-attended')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['roll_number'], '25881A6601')
        self.assertEqual(data[0]['department'], 'CSM')

        # Test GET /api/hod/registered-not-attended
        res_api = client.get('/api/hod/registered-not-attended')
        self.assertEqual(res_api.status_code, 200)
        data_api = json.loads(res_api.data)
        self.assertIsInstance(data_api, list)
        self.assertEqual(len(data_api), 1)

        # Test envelope format
        res_env = client.get('/api/hod/registered-not-attended?format=envelope')
        self.assertEqual(res_env.status_code, 200)
        data_env = json.loads(res_env.data)
        self.assertTrue(data_env['success'])
        self.assertEqual(data_env['department'], 'CSM')
        self.assertEqual(data_env['total'], 1)

    def test_hod_dashboard_renders_without_build_error(self):
        """Test that HOD dashboard renders without any BuildError and contains public.event_detail link."""
        reg1 = EventRegistration(
            event_id=self.event_completed.id,
            student_id=self.student_csm_absent.id,
            registration_code=str(uuid.uuid4())[:16],
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg1)
        db.session.commit()

        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['_user_id'] = str(self.hod_csm.id)
            sess['user_id'] = self.hod_csm.id
            sess['role'] = 'HOD'

        # Fetch HOD dashboard
        res = client.get('/hod/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Verify the table contains the link to public.event_detail with event_id
        expected_href = f'/events/{self.event_completed.id}'
        self.assertIn(expected_href, html)
        self.assertIn("Python Workshop", html)
        self.assertIn("Rahul Kumar", html)
        self.assertIn("25881A6601", html)

    def test_event_detail_by_id_and_by_slug(self):
        """Test that public.event_detail is accessible via both integer ID and slug."""
        client = self.app.test_client()

        # 1. Accessible via /events/<int:event_id>
        res_id = client.get(f'/events/{self.event_completed.id}')
        self.assertEqual(res_id.status_code, 200)
        self.assertIn("Python Workshop", res_id.data.decode('utf-8'))

        # 2. Accessible via /events/<slug>
        res_slug = client.get(f'/events/{self.event_completed.slug}')
        self.assertEqual(res_slug.status_code, 200)
        self.assertIn("Python Workshop", res_slug.data.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
