import os
import unittest
import uuid
from datetime import datetime, timedelta
from app import create_app
from config import Config
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    Announcement, Payment, PaymentStatus, AttendanceRecord, Certificate, CertificateStatus
)
from services.event_service import delete_expired_events

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost'

class TestCompletedEventsCleanup(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        uid = uuid.uuid4().hex[:6]
        # Create Organizer
        self.org_user = User(
            name=f"Club Lead {uid}",
            email=f"organizer_{uid}@college.edu",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        self.org_user.set_password("pass123")
        db.session.add(self.org_user)
        db.session.commit()

        self.org_profile = OrganizerProfile(
            user_id=self.org_user.id,
            organization_name="Tech Club",
            department="CSE",
            status="APPROVED",
            is_verified=True
        )
        db.session.add(self.org_profile)

        # Create Student
        self.student_user = User(
            name=f"John Student {uid}",
            email=f"student_{uid}@college.edu",
            role=UserRole.STUDENT,
            is_active=True
        )
        self.student_user.set_password("pass123")
        db.session.add(self.student_user)
        db.session.commit()

        self.student_profile = StudentProfile(
            user_id=self.student_user.id,
            roll_number=f"CSE{uid}",
            department="CSE",
            year=3,
            section="A"
        )
        db.session.add(self.student_profile)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_lifecycle_and_dynamic_status(self):
        now = datetime.utcnow()
        # 1. Upcoming Event
        upcoming = Event(
            title="Upcoming Summit",
            slug="upcoming-summit",
            description="Upcoming",
            organizer_id=self.org_user.id,
            event_type=EventType.SEMINAR,
            department="CSE",
            faculty_coordinator="Prof. A",
            venue="Hall 1",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
            registration_deadline=now + timedelta(days=1),
            status=EventStatus.APPROVED
        )

        # 2. Ongoing Event
        ongoing = Event(
            title="Live Hackathon",
            slug="live-hackathon",
            description="Ongoing",
            organizer_id=self.org_user.id,
            event_type=EventType.HACKATHON,
            department="CSE",
            faculty_coordinator="Prof. B",
            venue="Lab 1",
            start_time=now - timedelta(hours=2),
            end_time=now + timedelta(hours=4),
            registration_deadline=now - timedelta(hours=3),
            status=EventStatus.REGISTRATION_OPEN
        )

        # 3. Time-expired Event
        expired = Event(
            title="Past Workshop",
            slug="past-workshop",
            description="Expired",
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Prof. C",
            venue="Auditorium",
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=1),
            registration_deadline=now - timedelta(days=4),
            status=EventStatus.APPROVED
        )

        # 4. Explicitly Completed Event
        explicit_completed = Event(
            title="Completed Symposium",
            slug="completed-symposium",
            description="Completed",
            organizer_id=self.org_user.id,
            event_type=EventType.SYMPOSIUM,
            department="CSE",
            faculty_coordinator="Prof. D",
            venue="Hall 2",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=2),
            registration_deadline=now + timedelta(hours=12),
            status=EventStatus.COMPLETED
        )

        db.session.add_all([upcoming, ongoing, expired, explicit_completed])
        db.session.commit()

        # Verification of dynamic properties
        self.assertTrue(upcoming.is_upcoming)
        self.assertFalse(upcoming.is_completed)
        self.assertTrue(upcoming.is_active)

        self.assertTrue(ongoing.is_ongoing)
        self.assertFalse(ongoing.is_completed)
        self.assertTrue(ongoing.is_active)

        self.assertTrue(expired.is_completed)
        self.assertFalse(expired.is_active)
        self.assertEqual(expired.dynamic_lifecycle_status, EventStatus.COMPLETED)

        self.assertTrue(explicit_completed.is_completed)
        self.assertFalse(explicit_completed.is_active)
        self.assertEqual(explicit_completed.dynamic_lifecycle_status, EventStatus.COMPLETED)

    def test_student_dashboard_cleanup_of_completed_events_tickets_and_announcements(self):
        now = datetime.utcnow()
        # Active upcoming event
        active_ev = Event(
            title="Active AI Summit",
            slug="active-ai-summit",
            description="Active Summit",
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Dr. X",
            venue="Lab 101",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
            registration_deadline=now + timedelta(days=1),
            status=EventStatus.APPROVED
        )
        # Completed event
        completed_ev = Event(
            title="Completed Blockchain Boot",
            slug="completed-blockchain-boot",
            description="Completed Boot",
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Dr. Y",
            venue="Lab 102",
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=1),
            registration_deadline=now - timedelta(days=4),
            status=EventStatus.COMPLETED
        )
        db.session.add_all([active_ev, completed_ev])
        db.session.commit()

        # Create registrations
        reg_active = EventRegistration(
            event_id=active_ev.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.CONFIRMED,
            registration_code="REG-ACTIVE-101"
        )
        reg_completed = EventRegistration(
            event_id=completed_ev.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.CONFIRMED,
            registration_code="REG-COMPLETED-202"
        )
        db.session.add_all([reg_active, reg_completed])
        db.session.commit()

        # Create announcements for both events
        ann_active = Announcement(
            event_id=active_ev.id,
            author_id=self.org_user.id,
            title="Active Event Update",
            message="Bring your laptops!"
        )
        ann_completed = Announcement(
            event_id=completed_ev.id,
            author_id=self.org_user.id,
            title="Old Event Announcement",
            message="Thank you for participating last week."
        )
        db.session.add_all([ann_active, ann_completed])
        db.session.commit()

        # Login as student
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        # Check Student Dashboard
        res = self.client.get('/student/dashboard')
        self.assertEqual(res.status_code, 200)

        # 1. Active event is visible in upcoming passes
        self.assertIn(b"Active AI Summit", res.data)
        self.assertIn(b"REG-ACTIVE-101", res.data)
        self.assertIn(b"Active Event Update", res.data)

        # 2. Completed event is removed from active passes & active announcements
        self.assertNotIn(b"Completed Blockchain Boot", res.data)
        self.assertNotIn(b"Old Event Announcement", res.data)

        # Check Student My Events (Active tab)
        res_my_events_active = self.client.get('/student/my-events?tab=active')
        self.assertEqual(res_my_events_active.status_code, 200)
        self.assertIn(b"Active AI Summit", res_my_events_active.data)
        self.assertNotIn(b"Completed Blockchain Boot", res_my_events_active.data)

        # Check Student My Events (Completed history tab preserves historical records)
        res_my_events_history = self.client.get('/student/my-events?tab=completed')
        self.assertEqual(res_my_events_history.status_code, 200)
        self.assertIn(b"Completed Blockchain Boot", res_my_events_history.data)
        self.assertNotIn(b"Active AI Summit", res_my_events_history.data)

    def test_organizer_dashboard_removes_completed_and_preserves_database(self):
        now = datetime.utcnow()
        active_ev = Event(
            title="Spring Coding Contest",
            slug="spring-coding-contest",
            description="Contest",
            organizer_id=self.org_user.id,
            event_type=EventType.HACKATHON,
            department="CSE",
            faculty_coordinator="Prof. Z",
            venue="Lab 3",
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=6),
            registration_deadline=now + timedelta(days=4),
            status=EventStatus.APPROVED
        )
        past_ev = Event(
            title="Winter Web Dev",
            slug="winter-web-dev",
            description="Past Workshop",
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Prof. Z",
            venue="Lab 4",
            start_time=now - timedelta(days=10),
            end_time=now - timedelta(days=9),
            registration_deadline=now - timedelta(days=11),
            status=EventStatus.APPROVED
        )
        db.session.add_all([active_ev, past_ev])
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.org_user.id

        # 1. Organizer Dashboard (Active tab by default)
        res = self.client.get('/organizer/dashboard')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Spring Coding Contest", res.data)
        # Past/completed event is removed from active view
        self.assertNotIn(b"Winter Web Dev</a>", res.data)

        # 2. Organizer Dashboard (Completed tab)
        res_comp = self.client.get('/organizer/dashboard?tab=completed')
        self.assertEqual(res_comp.status_code, 200)
        self.assertIn(b"Winter Web Dev", res_comp.data)
        self.assertNotIn(b"Spring Coding Contest</a>", res_comp.data)

        # 3. Database records remain intact
        self.assertIsNotNone(Event.query.filter_by(slug="winter-web-dev").first())

    def test_manual_complete_action_by_organizer(self):
        now = datetime.utcnow()
        ev = Event(
            title="Ongoing Workshop",
            slug="ongoing-workshop-to-complete",
            description="To be marked complete",
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Prof. Z",
            venue="Lab 5",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            registration_deadline=now - timedelta(hours=2),
            status=EventStatus.APPROVED
        )
        db.session.add(ev)
        db.session.commit()

        self.assertFalse(ev.is_completed)

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.org_user.id

        # Mark complete
        res = self.client.post(f'/organizer/events/{ev.id}/complete', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Refresh event
        db.session.refresh(ev)
        self.assertEqual(ev.status, EventStatus.COMPLETED)
        self.assertTrue(ev.is_completed)

if __name__ == '__main__':
    unittest.main()
