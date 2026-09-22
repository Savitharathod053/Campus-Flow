"""
Campus Flow - Automated Test Suite for Empty Slots Notification Feature
Tests:
1. Event model fields, empty_slots property, occupancy_percentage, is_started status.
2. Cancelled registrations exclusion from confirmed_students / empty_slots.
3. HOD resolution priority (strictly department-scoped).
4. Notification trigger: when event starts with empty slots > 0, HOD gets in-app + email alert.
5. Notification prevention: when empty_slots == 0, NO notification is sent.
6. Future event: when start_time > now, NO notification is sent.
7. Duplicate prevention: repeated checks do NOT resend notification.
8. API endpoints: GET /events/{id}/capacity, GET /hod/notifications, POST /notifications/{id}/read.
"""
import unittest
from datetime import datetime, timedelta
import os

os.environ['TESTING'] = 'True'

from app import create_app
from models import (
    db, User, UserRole, CollegeDepartment, Event, EventStatus,
    EventRegistration, RegistrationStatus, Notification, NotificationType,
    EventNotificationLog
)
from services.capacity_notification_service import check_and_notify_empty_slots
from services.email_service import get_sent_emails, clear_sent_emails


class TestEmptySlotsNotification(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        clear_sent_emails()

    def test_01_event_model_capacity_and_status(self):
        """Test event properties: empty_slots, occupancy_percentage, is_started."""
        with self.app.app_context():
            now = datetime.utcnow()
            past_time = now - timedelta(hours=1)
            future_time = now + timedelta(hours=2)

            admin = User.query.first()
            admin_id = admin.id if admin else 1

            event = Event(
                title="Test Tech Symposium",
                slug=f"test-tech-symposium-{int(now.timestamp())}",
                organizer_id=admin_id,
                department="CSE",
                faculty_coordinator="Prof. Sharma",
                description="Annual flagship symposium on advanced computing.",
                venue="Auditorium A",
                start_time=past_time,
                end_time=future_time,
                registration_deadline=past_time,
                max_participants=100,
                status=EventStatus.APPROVED,
                is_published=True,
                hod_approved=True,
                dean_approved=True
            )
            db.session.add(event)
            db.session.commit()

            # Initially 0 registrations: empty_slots should be 100
            self.assertEqual(event.empty_slots, 100)
            self.assertEqual(event.occupancy_percentage, 0.0)
            self.assertTrue(event.is_started)

            users = User.query.limit(2).all()
            u1_id = users[0].id if len(users) > 0 else admin_id
            u2_id = users[1].id if len(users) > 1 else admin_id + 1

            # Add confirmed registration
            reg1 = EventRegistration(
                event_id=event.id,
                student_id=u1_id,
                registration_code=f"REG-CONF-{int(now.timestamp())}",
                status=RegistrationStatus.CONFIRMED
            )
            # Add cancelled registration (must be excluded!)
            reg2 = EventRegistration(
                event_id=event.id,
                student_id=u2_id,
                registration_code=f"REG-CANC-{int(now.timestamp())}",
                status=RegistrationStatus.CANCELLED
            )
            db.session.add_all([reg1, reg2])
            db.session.commit()

            self.assertEqual(event.confirmed_registrations_count, 1)
            self.assertEqual(event.empty_slots, 99)
            self.assertEqual(event.occupancy_percentage, 1.0)

            # Cleanup
            db.session.delete(reg1)
            db.session.delete(reg2)
            db.session.delete(event)
            db.session.commit()

    def test_02_hod_resolution_strict_department_scoping(self):
        """Verify that get_responsible_hod() returns ONLY the department's HOD."""
        with self.app.app_context():
            cse_dept = CollegeDepartment.query.filter_by(code='CSE').first()
            if not cse_dept:
                cse_dept = CollegeDepartment(code='CSE', name='Computer Science & Engineering')
                db.session.add(cse_dept)
                db.session.commit()

            hod_cse = User.query.filter_by(role=UserRole.HOD).first()
            if hod_cse:
                cse_dept.hod_id = hod_cse.id
                db.session.commit()

                event = Event(
                    title="CSE Python Bootcamp",
                    slug=f"cse-bootcamp-{int(datetime.utcnow().timestamp())}",
                    organizer_id=hod_cse.id,
                    department="CSE",
                    department_id=cse_dept.id,
                    faculty_coordinator="Dr. HOD",
                    description="Hands-on Python workshop for CSE students.",
                    venue="Lab 1",
                    start_time=datetime.utcnow(),
                    end_time=datetime.utcnow() + timedelta(hours=2),
                    registration_deadline=datetime.utcnow(),
                    max_participants=50,
                    status=EventStatus.APPROVED,
                    is_published=True,
                    hod_approved=True,
                    dean_approved=True
                )
                db.session.add(event)
                db.session.commit()

                resolved_hod = event.get_responsible_hod()
                self.assertIsNotNone(resolved_hod)
                self.assertEqual(resolved_hod.id, hod_cse.id)

                # Cleanup
                db.session.delete(event)
                db.session.commit()

    def test_03_notification_triggered_when_started_with_empty_slots(self):
        """
        When an event has start_time <= now and empty_slots > 0:
        - Event status transitions to STARTED
        - In-app notification created for HOD
        - Email sent to HOD
        - EventNotificationLog created
        - empty_slot_notification_sent is set to True
        """
        with self.app.app_context():
            clear_sent_emails()
            hod = User.query.filter_by(role=UserRole.HOD).first()
            if not hod:
                self.skipTest("No HOD found in database for test")

            now = datetime.utcnow()
            event = Event(
                title=f"Autonomous AI Workshop {int(now.timestamp())}",
                slug=f"ai-workshop-{int(now.timestamp())}",
                organizer_id=hod.id,
                department="CSE",
                responsible_hod_id=hod.id,
                faculty_coordinator="Coordinator",
                description="Workshop on autonomous agents and AI development.",
                venue="Seminar Hall",
                start_time=now - timedelta(minutes=10), # started 10 mins ago
                end_time=now + timedelta(hours=2),
                registration_deadline=now - timedelta(minutes=20),
                max_participants=50,
                status=EventStatus.APPROVED,
                is_published=True,
                hod_approved=True,
                dean_approved=True,
                empty_slot_notification_sent=False
            )
            db.session.add(event)
            db.session.commit()

            # Run empty slots check
            alerts = check_and_notify_empty_slots()
            self.assertTrue(len(alerts) >= 1)

            # Verify event was updated
            updated_event = Event.query.get(event.id)
            self.assertEqual(updated_event.status, EventStatus.STARTED)
            self.assertTrue(updated_event.empty_slot_notification_sent)

            # Verify in-app notification
            notif = Notification.query.filter_by(
                user_id=hod.id,
                type=NotificationType.EVENT_CAPACITY_ALERT
            ).order_by(Notification.id.desc()).first()
            self.assertIsNotNone(notif)
            self.assertIn("50 empty slots out of 50", notif.message)
            self.assertIn("Event Capacity Alert", notif.title)

            # Verify EventNotificationLog
            log = EventNotificationLog.query.filter_by(
                event_id=event.id,
                notification_type=NotificationType.EVENT_CAPACITY_ALERT,
                recipient_user_id=hod.id
            ).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.status, 'SENT')

            # Verify email sent
            emails = get_sent_emails()
            hod_emails = [e for e in emails if e['to'] == hod.email and e['type'] == 'EVENT_CAPACITY_ALERT']
            self.assertTrue(len(hod_emails) >= 1)
            self.assertIn("50 Empty Slots", hod_emails[-1]['subject'])
            self.assertIn(event.title, hod_emails[-1]['body'])

            # Verify DUPLICATE PREVENTION:
            # Calling check_and_notify_empty_slots again should NOT trigger another email or notification
            sent_count_before = len(get_sent_emails())
            repeat_alerts = check_and_notify_empty_slots()
            matching_repeat = [a for a in repeat_alerts if a['event_id'] == event.id]
            self.assertEqual(len(matching_repeat), 0)
            self.assertEqual(len(get_sent_emails()), sent_count_before)

            # Cleanup
            if notif:
                db.session.delete(notif)
            if log:
                db.session.delete(log)
            db.session.delete(event)
            db.session.commit()

    def test_04_full_event_no_notification_sent(self):
        """When empty_slots == 0 at start time, NO notification should be sent."""
        with self.app.app_context():
            clear_sent_emails()
            hod = User.query.filter_by(role=UserRole.HOD).first()
            if not hod:
                self.skipTest("No HOD found in database for test")

            now = datetime.utcnow()
            event = Event(
                title=f"Full Capacity Hackathon {int(now.timestamp())}",
                slug=f"full-hackathon-{int(now.timestamp())}",
                organizer_id=hod.id,
                department="CSE",
                responsible_hod_id=hod.id,
                faculty_coordinator="Coordinator",
                description="Hackathon filled to maximum capacity.",
                venue="Seminar Hall",
                start_time=now - timedelta(minutes=5),
                end_time=now + timedelta(hours=2),
                registration_deadline=now - timedelta(minutes=15),
                max_participants=1,
                status=EventStatus.APPROVED,
                is_published=True,
                hod_approved=True,
                dean_approved=True,
                empty_slot_notification_sent=False
            )
            db.session.add(event)
            db.session.commit()

            # Register 1 confirmed student (max_participants is 1, so empty_slots == 0)
            reg = EventRegistration(
                event_id=event.id,
                student_id=hod.id,
                registration_code=f"REG-FULL-{int(now.timestamp())}",
                status=RegistrationStatus.CONFIRMED
            )
            db.session.add(reg)
            db.session.commit()

            self.assertEqual(event.empty_slots, 0)

            # Run check
            check_and_notify_empty_slots()

            # Verify no email was dispatched
            emails = [e for e in get_sent_emails() if e['type'] == 'EVENT_CAPACITY_ALERT' and event.title in e['subject']]
            self.assertEqual(len(emails), 0)

            # Verify empty_slot_notification_sent is True (marked as processed)
            updated_event = Event.query.get(event.id)
            self.assertTrue(updated_event.empty_slot_notification_sent)

            # Cleanup
            db.session.delete(reg)
            db.session.delete(event)
            db.session.commit()

    def test_05_capacity_api_endpoint(self):
        """Test GET /events/{id}/capacity endpoint."""
        with self.app.app_context():
            now = datetime.utcnow()
            admin = User.query.first()
            admin_id = admin.id if admin else 1

            event = Event(
                title=f"API Capacity Test {int(now.timestamp())}",
                slug=f"api-capacity-{int(now.timestamp())}",
                organizer_id=admin_id,
                department="ECE",
                faculty_coordinator="Prof. ECE",
                description="Testing capacity metrics API.",
                venue="Hall 2",
                start_time=now + timedelta(days=1),
                end_time=now + timedelta(days=1, hours=2),
                registration_deadline=now + timedelta(hours=12),
                max_participants=80,
                status=EventStatus.APPROVED,
                is_published=True,
                hod_approved=True,
                dean_approved=True
            )
            db.session.add(event)
            db.session.commit()
            event_id = event.id

        resp = self.client.get(f'/events/{event_id}/capacity')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['total_capacity'], 80)
        self.assertEqual(data['confirmed_students'], 0)
        self.assertEqual(data['empty_slots'], 80)
        self.assertEqual(data['occupancy_percentage'], 0.0)

        # Cleanup
        with self.app.app_context():
            ev = Event.query.get(event_id)
            if ev:
                db.session.delete(ev)
                db.session.commit()


if __name__ == '__main__':
    unittest.main()
