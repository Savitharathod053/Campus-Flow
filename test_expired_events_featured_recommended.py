import unittest
import uuid
from datetime import datetime, timedelta
from app import create_app
from config import Config
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus
)

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost'

class TestExpiredEventsFeaturedAndRecommended(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        uid = uuid.uuid4().hex[:6]
        # Organizer
        self.org_user = User(
            name=f'Lead {uid}',
            email=f'org_{uid}@college.edu',
            role=UserRole.ORGANIZER,
            is_active=True
        )
        self.org_user.set_password('pass123')
        db.session.add(self.org_user)
        db.session.commit()

        self.org_profile = OrganizerProfile(
            user_id=self.org_user.id,
            organization_name='Tech Club',
            department='CSE',
            status='APPROVED',
            is_verified=True
        )
        db.session.add(self.org_profile)

        # Student
        self.student_user = User(
            name=f'Student {uid}',
            email=f'student_{uid}@college.edu',
            role=UserRole.STUDENT,
            is_active=True
        )
        self.student_user.set_password('pass123')
        db.session.add(self.student_user)
        db.session.commit()

        self.student_profile = StudentProfile(
            user_id=self.student_user.id,
            roll_number=f'CSE{uid}',
            department='CSE',
            year=3,
            section='A'
        )
        db.session.add(self.student_profile)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_featured_and_recommended_exclude_expired_events(self):
        now = datetime.utcnow()

        # 1. Valid Upcoming Event (Future start, future end, future deadline, dual-approved, published)
        valid_ev = Event(
            title='Valid Future Summit 2026',
            slug='valid-future-summit-2026',
            description='Future event description',
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department='CSE',
            faculty_coordinator='Prof. Alpha',
            venue='Hall A',
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=6),
            registration_deadline=now + timedelta(days=4),
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )

        # 2. Expired Event: end_time in the past
        expired_time_ev = Event(
            title='Expired By EndTime Hackathon',
            slug='expired-by-endtime-hackathon',
            description='Past event end time',
            organizer_id=self.org_user.id,
            event_type=EventType.HACKATHON,
            department='CSE',
            faculty_coordinator='Prof. Beta',
            venue='Lab B',
            start_time=now - timedelta(days=5),
            end_time=now - timedelta(days=3),
            registration_deadline=now - timedelta(days=6),
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )

        # 3. Expired Event: status explicitly COMPLETED
        completed_status_ev = Event(
            title='Completed Status Symposium',
            slug='completed-status-symposium',
            description='Completed status event',
            organizer_id=self.org_user.id,
            event_type=EventType.SYMPOSIUM,
            department='CSE',
            faculty_coordinator='Prof. Gamma',
            venue='Auditorium',
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
            registration_deadline=now + timedelta(days=1),
            status=EventStatus.COMPLETED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )

        # 4. Expired Event: Registration deadline in the past (even if end_time in future)
        expired_deadline_ev = Event(
            title='Deadline Passed Seminar',
            slug='deadline-passed-seminar',
            description='Registration deadline passed',
            organizer_id=self.org_user.id,
            event_type=EventType.SEMINAR,
            department='CSE',
            faculty_coordinator='Prof. Delta',
            venue='Hall C',
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
            registration_deadline=now - timedelta(hours=2),
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )

        # 5. Non-upcoming Event: start_time in the past (already started/ongoing)
        started_ev = Event(
            title='Already Started Coding Sprint',
            slug='already-started-coding-sprint',
            description='Event already started',
            organizer_id=self.org_user.id,
            event_type=EventType.TECHNICAL,
            department='CSE',
            faculty_coordinator='Prof. Epsilon',
            venue='Lab D',
            start_time=now - timedelta(hours=4),
            end_time=now + timedelta(days=1),
            registration_deadline=now - timedelta(hours=5),
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )

        db.session.add_all([valid_ev, expired_time_ev, completed_status_ev, expired_deadline_ev, started_ev])
        db.session.commit()

        # Check Landing Page - Featured Upcoming Events
        res_home = self.client.get('/')
        self.assertEqual(res_home.status_code, 200)

        # The valid upcoming event MUST be present
        self.assertIn(b'Valid Future Summit 2026', res_home.data)

        # All expired, completed, deadline-passed, and already-started events MUST NOT be present
        self.assertNotIn(b'Expired By EndTime Hackathon', res_home.data)
        self.assertNotIn(b'Completed Status Symposium', res_home.data)
        self.assertNotIn(b'Deadline Passed Seminar', res_home.data)
        self.assertNotIn(b'Already Started Coding Sprint', res_home.data)

        # Login as student and check Recommended For You on Dashboard
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        res_dash = self.client.get('/student/dashboard')
        self.assertEqual(res_dash.status_code, 200)

        # The valid upcoming event MUST be in Recommended For You
        self.assertIn(b'Valid Future Summit 2026', res_dash.data)

        # All expired, completed, deadline-passed, and already-started events MUST NOT be in Recommended For You
        self.assertNotIn(b'Expired By EndTime Hackathon', res_dash.data)
        self.assertNotIn(b'Completed Status Symposium', res_dash.data)
        self.assertNotIn(b'Deadline Passed Seminar', res_dash.data)
        self.assertNotIn(b'Already Started Coding Sprint', res_dash.data)

    def test_registered_event_not_in_recommended(self):
        now = datetime.utcnow()
        registered_ev = Event(
            title='Registered Upcoming Bootcamp',
            slug='registered-upcoming-bootcamp',
            description='Bootcamp',
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department='CSE',
            faculty_coordinator='Prof. Omega',
            venue='Hall Z',
            start_time=now + timedelta(days=10),
            end_time=now + timedelta(days=11),
            registration_deadline=now + timedelta(days=8),
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(registered_ev)
        db.session.commit()

        # Student registers for this event
        reg = EventRegistration(
            event_id=registered_ev.id,
            student_id=self.student_user.id,
            registration_code='REG-TEST-999',
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg)
        db.session.commit()

        # Login as student
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        res_dash = self.client.get('/student/dashboard')
        self.assertEqual(res_dash.status_code, 200)

        # It should appear in 'Your Upcoming Events & Passes'
        self.assertIn(b'Your Upcoming Events & Passes', res_dash.data)
        self.assertIn(b'REG-TEST-999', res_dash.data)

        # But it must NOT be in 'Recommended For You'
        learn_more_link = f'/events/{registered_ev.slug}'.encode('utf-8')
        self.assertNotIn(learn_more_link, res_dash.data)

if __name__ == '__main__':
    unittest.main()
