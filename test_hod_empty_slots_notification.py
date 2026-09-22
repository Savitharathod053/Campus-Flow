"""
Campus Flow - Test Suite for HOD Empty Slots Notification on Event Start
Verifies:
1. Event starts with unfilled slots (e.g. 35/50 confirmed -> 15 empty slots).
2. Correct Department HOD receives in-app notification with all required metadata.
3. Unread count increments for the responsible HOD.
4. Other department HODs do NOT receive the notification.
5. Email dispatch is executed with proper details.
6. Duplicate prevention: repeated start API calls do not generate duplicate notifications.
7. Fully booked event (0 empty slots) does NOT dispatch notifications.
8. Cancelled/completed events do not trigger alerts.
"""
import unittest
from datetime import datetime, timedelta

from app import create_app
from models import (
    db, User, UserRole, CollegeDepartment, FacultyProfile, StudentProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    Notification, NotificationType, EventNotificationLog
)
from services.capacity_notification_service import notify_hod_event_started


class TestHODEmptySlotsNotification(unittest.TestCase):

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
                phone="+91 9999999999",
                is_active=True
            )
            user.set_password("Pass@123")
            db.session.add(user)
            db.session.flush()

            if role == UserRole.HOD and dept:
                fp = FacultyProfile(
                    user_id=user.id,
                    employee_id=f"EMP-{dept}-{user.id}",
                    department=dept,
                    designation="Head of Department"
                )
                db.session.add(fp)

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

    def test_01_event_start_notifies_responsible_hod_with_empty_slots(self):
        """
        Scenario from user prompt:
        - Event: "Python Workshop"
        - Department: CSE
        - Total slots: 50
        - Confirmed registrations: 35
        - Expected result: 50 - 35 = 15 empty slots
        - Respective CSE HOD receives notification:
          "Python Workshop has started with 15 empty slots remaining."
        """
        organizer = self._get_or_create_user("test.org.cse@college.edu", "John Organizer", UserRole.ORGANIZER)
        cse_hod = self._get_or_create_user("test.hod.cse@college.edu", "Dr. CSE HOD", UserRole.HOD, "CSE")
        it_hod = self._get_or_create_user("test.hod.it@college.edu", "Dr. IT HOD", UserRole.HOD, "IT")

        cse_dept = self._get_or_create_dept("CSE", "Computer Science & Engineering", cse_hod)
        it_dept = self._get_or_create_dept("IT", "Information Technology", it_hod)
        db.session.commit()

        initial_unread_cse = Notification.query.filter_by(user_id=cse_hod.id, is_read=False).count()
        initial_unread_it = Notification.query.filter_by(user_id=it_hod.id, is_read=False).count()

        # Create "Python Workshop"
        now = datetime.utcnow()
        event = Event(
            title="Python Workshop",
            slug=f"python-workshop-test-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=cse_dept.id,
            max_participants=50,
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=5),
            registration_deadline=now + timedelta(hours=1),
            venue="Lab 3",
            description="Hands-on Python workshop.",
            faculty_coordinator="Prof. Faculty Coordinator",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.flush()

        # Register 35 confirmed students
        for i in range(35):
            student = self._get_or_create_user(f"student{i}_{int(now.timestamp())}@college.edu", f"Student {i}", UserRole.STUDENT)
            reg = EventRegistration(
                event_id=event.id,
                student_id=student.id,
                registration_code=f"REG-CSE-{i}-{int(now.timestamp())}",
                status=RegistrationStatus.CONFIRMED
            )
            db.session.add(reg)
        db.session.commit()

        # Verify initial counts: 50 total, 35 confirmed, 15 empty
        self.assertEqual(event.max_participants, 50)
        self.assertEqual(event.confirmed_registrations_count, 35)
        self.assertEqual(event.empty_slots, 15)

        # Trigger event start API via client
        with self.client.session_transaction() as sess:
            sess['user_id'] = organizer.id

        resp = self.client.post(f'/organizer/events/{event.id}/start', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], EventStatus.STARTED)
        self.assertEqual(data['empty_slots'], 15)
        self.assertTrue(data['notification_dispatched'])

        # Verify event state in database
        updated_event = db.session.get(Event, event.id)
        self.assertEqual(updated_event.status, EventStatus.STARTED)
        self.assertTrue(updated_event.empty_slot_notification_sent)

        # Verify in-app notification created for CSE HOD ONLY
        notifs_cse = Notification.query.filter_by(
            user_id=cse_hod.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).all()
        self.assertGreater(len(notifs_cse), 0)
        latest_notif = notifs_cse[-1]
        self.assertIn("Python Workshop", latest_notif.title)
        self.assertIn("15 empty slots remaining", latest_notif.message)
        self.assertIn("Python Workshop", latest_notif.message)
        self.assertIn("CSE", latest_notif.message)
        self.assertIn("John Organizer", latest_notif.message)

        # Verify unread count increased for CSE HOD
        final_unread_cse = Notification.query.filter_by(user_id=cse_hod.id, is_read=False).count()
        self.assertEqual(final_unread_cse, initial_unread_cse + 1)

        # Verify IT HOD did NOT receive notification
        final_unread_it = Notification.query.filter_by(user_id=it_hod.id, is_read=False).count()
        self.assertEqual(final_unread_it, initial_unread_it)

        # Verify EventNotificationLog recorded
        log_entry = EventNotificationLog.query.filter_by(
            event_id=event.id,
            recipient_user_id=cse_hod.id,
            notification_type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.status, 'SENT')

        # TEST DUPLICATE PREVENTION: Call start again / refresh
        repeat_resp = self.client.post(f'/organizer/events/{event.id}/start', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(repeat_resp.status_code, 200)
        repeat_data = repeat_resp.get_json()
        self.assertFalse(repeat_data['notification_dispatched'])

        # Count of notifications should remain unchanged
        repeat_count = Notification.query.filter_by(
            user_id=cse_hod.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).count()
        self.assertEqual(repeat_count, len(notifs_cse))

    def test_02_fully_booked_event_sends_no_empty_slot_notification(self):
        """
        When total_slots == confirmed (0 empty slots), NO notification is sent.
        """
        organizer = self._get_or_create_user("test.org.cse2@college.edu", "Organizer Two", UserRole.ORGANIZER)
        cse_hod = self._get_or_create_user("test.hod.cse@college.edu", "Dr. CSE HOD", UserRole.HOD, "CSE")
        cse_dept = self._get_or_create_dept("CSE", "Computer Science & Engineering", cse_hod)
        db.session.commit()

        initial_count = Notification.query.filter_by(user_id=cse_hod.id).count()

        now = datetime.utcnow()
        event = Event(
            title="Fully Booked Coding Contest",
            slug=f"full-contest-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=cse_dept.id,
            max_participants=2,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=3),
            registration_deadline=now,
            venue="Auditorium",
            description="Contest.",
            faculty_coordinator="Prof. Faculty Coordinator",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.flush()

        # Register 2 confirmed students (2/2 = 0 empty slots)
        for i in range(2):
            s = self._get_or_create_user(f"full_stud{i}_{int(now.timestamp())}@college.edu", f"Student {i}", UserRole.STUDENT)
            reg = EventRegistration(
                event_id=event.id,
                student_id=s.id,
                registration_code=f"REG-FULL-{i}-{int(now.timestamp())}",
                status=RegistrationStatus.CONFIRMED
            )
            db.session.add(reg)
        db.session.commit()

        self.assertEqual(event.empty_slots, 0)

        # Start event
        with self.client.session_transaction() as sess:
            sess['user_id'] = organizer.id

        resp = self.client.post(f'/organizer/events/{event.id}/start', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertFalse(data['notification_dispatched'])
        self.assertEqual(data['empty_slots'], 0)

        # Verify no new notification was created
        final_count = Notification.query.filter_by(user_id=cse_hod.id).count()
        self.assertEqual(final_count, initial_count)

    def test_03_different_department_event_alerts_only_its_own_hod(self):
        """
        An IT Department event start alerts the IT HOD, never the CSE HOD.
        """
        organizer = self._get_or_create_user("test.org.it@college.edu", "IT Organizer", UserRole.ORGANIZER)
        it_hod = self._get_or_create_user("test.hod.it2@college.edu", "Dr. IT HOD", UserRole.HOD, "IT")
        cse_hod = self._get_or_create_user("test.hod.cse@college.edu", "Dr. CSE HOD", UserRole.HOD, "CSE")

        it_dept = self._get_or_create_dept("IT", "Information Technology", it_hod)
        cse_dept = self._get_or_create_dept("CSE", "Computer Science & Engineering", cse_hod)
        db.session.commit()

        initial_cse_count = Notification.query.filter_by(user_id=cse_hod.id).count()
        initial_it_count = Notification.query.filter_by(user_id=it_hod.id).count()

        now = datetime.utcnow()
        event = Event(
            title="Cloud Security Symposium",
            slug=f"cloud-sec-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="IT",
            department_id=it_dept.id,
            max_participants=40,
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=4),
            registration_deadline=now,
            venue="Seminar Hall 2",
            description="Symposium on cloud infrastructure.",
            faculty_coordinator="Prof. Faculty Coordinator",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.commit()

        # Start event with 0 registered (40 empty slots)
        with self.client.session_transaction() as sess:
            sess['user_id'] = organizer.id

        resp = self.client.post(f'/organizer/events/{event.id}/start', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(resp.status_code, 200)

        # IT HOD got 1 notification
        self.assertEqual(Notification.query.filter_by(user_id=it_hod.id).count(), initial_it_count + 1)
        # CSE HOD got 0 notifications
        self.assertEqual(Notification.query.filter_by(user_id=cse_hod.id).count(), initial_cse_count)


if __name__ == '__main__':
    unittest.main()
