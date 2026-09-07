import unittest
import uuid
from datetime import datetime, timedelta
from app import create_app
from config import Config
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    Announcement
)
from services.event_service import delete_expired_event_announcements

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost'

class TestExpiredEventAnnouncements(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        uid = uuid.uuid4().hex[:6]
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
            roll_number=f"ROLL-{uid}",
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

    def test_expired_event_announcements_deleted_on_student_dashboard(self):
        now = datetime.utcnow()
        uid = uuid.uuid4().hex[:6]

        active_event = Event(
            organizer_id=self.org_user.id,
            title=f"Active Workshop {uid}",
            slug=f"active-slug-{uid}",
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            description="Active Event Description",
            venue="Hall A",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
            registration_deadline=now + timedelta(days=1),
            event_type=EventType.WORKSHOP,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(active_event)
        db.session.flush()

        expired_event = Event(
            organizer_id=self.org_user.id,
            title=f"Expired Hackathon {uid}",
            slug=f"expired-slug-{uid}",
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            description="Expired Event Description",
            venue="Lab B",
            start_time=now - timedelta(days=5),
            end_time=now - timedelta(days=2),
            registration_deadline=now - timedelta(days=6),
            event_type=EventType.HACKATHON,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(expired_event)
        db.session.flush()

        ann_active = Announcement(
            event_id=active_event.id,
            author_id=self.org_user.id,
            title=f"Active Broadcast {uid}",
            message="Active Event Announcement Message"
        )
        ann_expired = Announcement(
            event_id=expired_event.id,
            author_id=self.org_user.id,
            title=f"Expired Broadcast {uid}",
            message="Expired Event Announcement Message"
        )
        db.session.add_all([ann_active, ann_expired])
        db.session.commit()

        reg_active = EventRegistration(
            event_id=active_event.id,
            student_id=self.student_user.id,
            registration_code=f"REG-ACT-{uid}",
            status=RegistrationStatus.CONFIRMED
        )
        reg_expired = EventRegistration(
            event_id=expired_event.id,
            student_id=self.student_user.id,
            registration_code=f"REG-EXP-{uid}",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add_all([reg_active, reg_expired])
        db.session.commit()

        self.assertIsNotNone(Announcement.query.get(ann_active.id))
        self.assertIsNotNone(Announcement.query.get(ann_expired.id))

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id
            sess['role'] = UserRole.STUDENT

        resp = self.client.get('/student/dashboard')
        self.assertEqual(resp.status_code, 200)

        self.assertIsNone(Announcement.query.get(ann_expired.id))
        self.assertIsNotNone(Announcement.query.get(ann_active.id))

        html = resp.get_data(as_text=True)
        self.assertIn(f"Active Broadcast {uid}", html)
        self.assertNotIn(f"Expired Broadcast {uid}", html)

    def test_complete_event_deletes_announcements(self):
        now = datetime.utcnow()
        uid = uuid.uuid4().hex[:6]

        event = Event(
            organizer_id=self.org_user.id,
            title=f"To Complete Event {uid}",
            slug=f"complete-slug-{uid}",
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            description="Will be marked complete",
            venue="Auditorium",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=2),
            registration_deadline=now + timedelta(hours=12),
            event_type=EventType.SEMINAR,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(event)
        db.session.flush()

        ann = Announcement(
            event_id=event.id,
            author_id=self.org_user.id,
            title=f"Complete Broadcast {uid}",
            message="Broadcast before completion"
        )
        db.session.add(ann)
        db.session.commit()

        self.assertIsNotNone(Announcement.query.get(ann.id))

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.org_user.id
            sess['role'] = UserRole.ORGANIZER

        resp = self.client.post(f'/organizer/events/{event.id}/complete', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        self.assertIsNone(Announcement.query.get(ann.id))

    def test_delete_expired_event_announcements_service(self):
        now = datetime.utcnow()
        uid = uuid.uuid4().hex[:6]

        ev_expired = Event(
            organizer_id=self.org_user.id,
            title=f"Service Expired Event {uid}",
            slug=f"serv-exp-slug-{uid}",
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            description="Expired",
            venue="Room 101",
            start_time=now - timedelta(days=4),
            end_time=now - timedelta(days=1),
            registration_deadline=now - timedelta(days=5),
            event_type=EventType.WORKSHOP,
            status=EventStatus.APPROVED
        )
        ev_active = Event(
            organizer_id=self.org_user.id,
            title=f"Service Active Event {uid}",
            slug=f"serv-act-slug-{uid}",
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            description="Active",
            venue="Room 102",
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=2),
            registration_deadline=now + timedelta(hours=5),
            event_type=EventType.WORKSHOP,
            status=EventStatus.APPROVED
        )
        db.session.add_all([ev_expired, ev_active])
        db.session.flush()

        ann1 = Announcement(event_id=ev_expired.id, author_id=self.org_user.id, title="Exp", message="Exp msg")
        ann2 = Announcement(event_id=ev_active.id, author_id=self.org_user.id, title="Act", message="Act msg")
        db.session.add_all([ann1, ann2])
        db.session.commit()

        deleted = delete_expired_event_announcements()
        self.assertEqual(deleted, 1)
        self.assertIsNone(Announcement.query.get(ann1.id))
        self.assertIsNotNone(Announcement.query.get(ann2.id))

if __name__ == '__main__':
    unittest.main()
