"""
Campus Flow - End-to-End Test Suite for Manual Event Start & Department-Wise HOD Notifications
Verifies:
1. Event does NOT start automatically by time/scheduler.
2. Only Organizer (or Admin) can manually trigger 'Start Event'; non-organizer gets 403 Forbidden.
3. Event status successfully transitions from 'Scheduled'/'APPROVED' to 'Started'.
4. Exact calculation of:
   - Total event slots
   - Online registered students
   - On-spot registrations
   - Total occupied slots
   - Remaining/empty slots
5. Department-wise separation:
   - CSE HOD receives only CSE counts.
   - ECE HOD receives only ECE counts.
   - Mechanical HOD (0 students) receives NO notification.
6. Notification formatting matches specification exactly.
7. Duplicate prevention on page refresh or repeat clicks.
"""
import unittest
from datetime import datetime, timedelta

from app import create_app
from models import (
    db, User, UserRole, CollegeDepartment, FacultyProfile, StudentProfile,
    Event, EventStatus, EventRegistration, RegistrationStatus,
    Notification, NotificationType, EventNotificationLog
)
from services.capacity_notification_service import check_and_notify_empty_slots


class TestManualEventStartWorkflow(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def _get_or_create_user(self, email, name, role, dept=None):
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                name=name,
                email=email,
                role=role,
                phone="+91 9888888888",
                is_active=True
            )
            user.set_password("Pass@123")
            db.session.add(user)
            db.session.flush()

            if role == UserRole.HOD and dept:
                fp = FacultyProfile(
                    user_id=user.id,
                    employee_id=f"EMP-HOD-{dept}-{user.id}",
                    department=dept,
                    designation="Head of Department"
                )
                db.session.add(fp)

            if role == UserRole.STUDENT:
                sp = StudentProfile(
                    user_id=user.id,
                    roll_number=f"ROLL-{user.id}",
                    department=dept or "CSE",
                    year=3,
                    section="A"
                )
                db.session.add(sp)

        return user

    def _get_or_create_dept(self, code, name, hod_user):
        dept = CollegeDepartment.query.filter_by(code=code).first()
        if not dept:
            dept = CollegeDepartment(
                code=code,
                name=name,
                hod_id=hod_user.id if hod_user else None,
                is_active=True
            )
            db.session.add(dept)
            db.session.flush()
        else:
            if hod_user and dept.hod_id != hod_user.id:
                dept.hod_id = hod_user.id
                db.session.add(dept)
                db.session.flush()
        return dept

    def test_full_manual_event_start_and_department_notifications(self):
        """
        Full lifecycle test simulating:
        Event: AI Workshop
        Total Slots: 100 (max 80 + 20 spot)
        CSE Students: 35 Online, 5 Spot (Total Occupied = 40)
        ECE Students: 20 Online, 2 Spot (Total Occupied = 22)
        MECH Dept: 0 Students
        """
        now = datetime.utcnow()
        timestamp = int(now.timestamp())

        # 1. Setup Users and Departments
        organizer = self._get_or_create_user(f"org_ai_{timestamp}@college.edu", "AI Organizer", UserRole.ORGANIZER)
        unauthorized_user = self._get_or_create_user(f"unauth_user_{timestamp}@college.edu", "Other User", UserRole.ORGANIZER)
        
        cse_hod = self._get_or_create_user(f"hod_cse_{timestamp}@college.edu", "Dr. CSE Head", UserRole.HOD, "CSE")
        ece_hod = self._get_or_create_user(f"hod_ece_{timestamp}@college.edu", "Dr. ECE Head", UserRole.HOD, "ECE")
        mech_hod = self._get_or_create_user(f"hod_mech_{timestamp}@college.edu", "Dr. MECH Head", UserRole.HOD, "MECH")

        cse_dept = self._get_or_create_dept("CSE", "Computer Science and Engineering", cse_hod)
        ece_dept = self._get_or_create_dept("ECE", "Electronics and Communication Engineering", ece_hod)
        mech_dept = self._get_or_create_dept("MECH", "Mechanical Engineering", mech_hod)
        db.session.commit()

        # Initial unread notifications
        init_cse_notifs = Notification.query.filter_by(user_id=cse_hod.id).count()
        init_ece_notifs = Notification.query.filter_by(user_id=ece_hod.id).count()
        init_mech_notifs = Notification.query.filter_by(user_id=mech_hod.id).count()

        # 2. Create Event: AI Workshop
        event = Event(
            title="AI Workshop",
            slug=f"ai-workshop-{timestamp}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=cse_dept.id,
            allowed_departments="CSE,ECE",
            max_participants=100,
            spot_registration_slots=0,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=4),
            registration_deadline=now + timedelta(minutes=30),
            venue="Main Tech Hall",
            description="Deep Dive into Generative AI & Robotics",
            faculty_coordinator="Prof. AI Lead",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.flush()

        # 3. Register CSE students: 35 Online, 5 Spot
        for i in range(35):
            s = self._get_or_create_user(f"cse_online_{i}_{timestamp}@college.edu", f"CSE Online {i}", UserRole.STUDENT, "CSE")
            reg = EventRegistration(
                event_id=event.id,
                student_id=s.id,
                registration_code=f"REG-CSE-ON-{i}-{timestamp}",
                status=RegistrationStatus.CONFIRMED,
                registration_type="ONLINE"
            )
            db.session.add(reg)

        for i in range(5):
            s = self._get_or_create_user(f"cse_spot_{i}_{timestamp}@college.edu", f"CSE Spot {i}", UserRole.STUDENT, "CSE")
            reg = EventRegistration(
                event_id=event.id,
                student_id=s.id,
                registration_code=f"REG-CSE-SP-{i}-{timestamp}",
                status=RegistrationStatus.CONFIRMED,
                registration_type="SPOT"
            )
            db.session.add(reg)

        # 4. Register ECE students: 20 Online, 2 Spot
        for i in range(20):
            s = self._get_or_create_user(f"ece_online_{i}_{timestamp}@college.edu", f"ECE Online {i}", UserRole.STUDENT, "ECE")
            reg = EventRegistration(
                event_id=event.id,
                student_id=s.id,
                registration_code=f"REG-ECE-ON-{i}-{timestamp}",
                status=RegistrationStatus.CONFIRMED,
                registration_type="ONLINE"
            )
            db.session.add(reg)

        for i in range(2):
            s = self._get_or_create_user(f"ece_spot_{i}_{timestamp}@college.edu", f"ECE Spot {i}", UserRole.STUDENT, "ECE")
            reg = EventRegistration(
                event_id=event.id,
                student_id=s.id,
                registration_code=f"REG-ECE-SP-{i}-{timestamp}",
                status=RegistrationStatus.CONFIRMED,
                registration_type="SPOT"
            )
            db.session.add(reg)

        db.session.commit()

        # 5. VERIFY REQUIREMENT 1: Event does NOT automatically start on background check
        check_and_notify_empty_slots(self.app)
        db.session.refresh(event)
        self.assertNotEqual(event.status, EventStatus.STARTED, "Event must not be automatically started by scheduler")
        self.assertFalse(event.empty_slot_notification_sent, "Notifications must not be automatically sent by scheduler")

        # 6. VERIFY REQUIREMENT 2: Non-organizer cannot start the event
        with self.client.session_transaction() as sess:
            sess['user_id'] = unauthorized_user.id

        unauth_resp = self.client.post(
            f'/organizer/events/{event.id}/start',
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )
        self.assertEqual(unauth_resp.status_code, 403, "Non-organizer must receive 403 Forbidden")

        # 7. VERIFY REQUIREMENT 3: Organizer manually starts the event
        with self.client.session_transaction() as sess:
            sess['user_id'] = organizer.id

        start_resp = self.client.post(
            f'/organizer/events/{event.id}/start',
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )
        self.assertEqual(start_resp.status_code, 200)
        data = start_resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], EventStatus.STARTED)
        self.assertEqual(data['total_slots'], 100)
        self.assertEqual(data['online_registrations'], 55)  # 35 + 20
        self.assertEqual(data['spot_registrations'], 7)     # 5 + 2
        self.assertEqual(data['total_occupied'], 62)       # 55 + 7
        self.assertEqual(data['empty_slots'], 38)          # 100 - 62
        self.assertTrue(data['notification_dispatched'])

        # 8. VERIFY REQUIREMENT 4: Database status updated to 'Started'
        db.session.refresh(event)
        self.assertEqual(event.status, EventStatus.STARTED)
        self.assertTrue(event.empty_slot_notification_sent)

        # 9. VERIFY REQUIREMENT 5: Department-wise Notification Separation
        # A) CSE HOD Notifications
        cse_notifs = Notification.query.filter_by(
            user_id=cse_hod.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).all()
        self.assertEqual(len(cse_notifs), 1, "CSE HOD must receive exactly 1 notification")
        cse_msg = cse_notifs[0].message
        self.assertIn("Event Started: AI Workshop", cse_msg)
        self.assertTrue("Computer Science" in cse_msg)
        self.assertIn("Total Event Slots: 100", cse_msg)
        self.assertIn("Online Registrations: 35", cse_msg)
        self.assertIn("On-Spot Registrations: 5", cse_msg)
        self.assertIn("Total Occupied: 40", cse_msg)
        self.assertIn("Empty Slots: 10", cse_msg)

        # B) ECE HOD Notifications
        ece_notifs = Notification.query.filter_by(
            user_id=ece_hod.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).all()
        self.assertEqual(len(ece_notifs), 1, "ECE HOD must receive exactly 1 notification")
        ece_msg = ece_notifs[0].message
        self.assertIn("Event Started: AI Workshop", ece_msg)
        self.assertTrue("Electronics" in ece_msg)
        self.assertIn("Total Event Slots: 100", ece_msg)
        self.assertIn("Online Registrations: 20", ece_msg)
        self.assertIn("On-Spot Registrations: 2", ece_msg)
        self.assertIn("Total Occupied: 22", ece_msg)
        self.assertIn("Empty Slots: 28", ece_msg)

        # C) MECH HOD Notifications (No students -> NO notification)
        mech_notifs = Notification.query.filter_by(
            user_id=mech_hod.id,
            event_id=event.id
        ).all()
        self.assertEqual(len(mech_notifs), 0, "MECH HOD must receive 0 notifications because no students are involved")

        # 10. VERIFY REQUIREMENT 6: Duplicate Prevention on repeat Start / refresh
        repeat_resp = self.client.post(
            f'/organizer/events/{event.id}/start',
            headers={'X-Requested-With': 'XMLHttpRequest'}
        )
        self.assertEqual(repeat_resp.status_code, 200)
        repeat_data = repeat_resp.get_json()
        self.assertFalse(repeat_data['notification_dispatched'], "Repeated start must not dispatch duplicate notifications")

        cse_count_after_repeat = Notification.query.filter_by(
            user_id=cse_hod.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).count()
        self.assertEqual(cse_count_after_repeat, 1, "CSE HOD notification count must remain 1")

        ece_count_after_repeat = Notification.query.filter_by(
            user_id=ece_hod.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).count()
        self.assertEqual(ece_count_after_repeat, 1, "ECE HOD notification count must remain 1")


if __name__ == '__main__':
    unittest.main()
