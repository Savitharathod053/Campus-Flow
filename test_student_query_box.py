import unittest
from datetime import datetime, timedelta
from app import create_app
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile, Event, EventStatus,
    EventType, Notification, NotificationType, EventQuery, QueryStatus, CollegeDepartment
)


class TestStudentQueryBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Unique suffix for test isolation
        ts = int(datetime.utcnow().timestamp() * 1000)

        # 1. Create College Department
        self.dept = CollegeDepartment.query.filter_by(code="CSE").first()
        if not self.dept:
            self.dept = CollegeDepartment(code="CSE", name="Computer Science and Engineering")
            db.session.add(self.dept)
            db.session.commit()

        # 2. Create Organizer
        self.organizer = User(
            name=f"Organizer John {ts}",
            email=f"org_john_{ts}@campusflow.edu",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        self.organizer.set_password("pass123")
        db.session.add(self.organizer)
        db.session.commit()

        # Another organizer for data isolation test
        self.other_organizer = User(
            name=f"Organizer Alice {ts}",
            email=f"org_alice_{ts}@campusflow.edu",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        self.other_organizer.set_password("pass123")
        db.session.add(self.other_organizer)
        db.session.commit()

        # 3. Create Student
        self.student = User(
            name=f"Student Bob {ts}",
            email=f"student_bob_{ts}@campusflow.edu",
            role=UserRole.STUDENT,
            is_active=True
        )
        self.student.set_password("pass123")
        db.session.add(self.student)
        db.session.commit()

        self.student_profile = StudentProfile(
            user_id=self.student.id,
            roll_number=f"24CSE{ts % 10000:04d}",
            department="CSE",
            year=3,
            section="A"
        )
        db.session.add(self.student_profile)
        db.session.commit()

        # 4. Create Approved Event for Organizer John
        self.event = Event(
            title=f"AI Hackathon {ts}",
            slug=f"ai-hackathon-{ts}",
            organizer_id=self.organizer.id,
            department="CSE",
            description="Annual AI Hackathon coding competition.",
            event_type=EventType.HACKATHON,
            faculty_coordinator="Dr. Coordinator",
            start_time=datetime.utcnow() + timedelta(days=2),
            end_time=datetime.utcnow() + timedelta(days=3),
            registration_deadline=datetime.utcnow() + timedelta(days=1),
            venue="Main Tech Hall",
            max_participants=100,
            is_free=True,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(self.event)
        db.session.commit()

    def tearDown(self):
        try:
            EventQuery.query.filter(
                (EventQuery.student_id == self.student.id) |
                (EventQuery.organizer_id.in_([self.organizer.id, self.other_organizer.id]))
            ).delete()
            Notification.query.filter(
                Notification.user_id.in_([self.student.id, self.organizer.id, self.other_organizer.id])
            ).delete()
            if self.event and self.event.id:
                Event.query.filter_by(id=self.event.id).delete()
            if self.student_profile and self.student_profile.id:
                StudentProfile.query.filter_by(id=self.student_profile.id).delete()
            User.query.filter(
                User.id.in_([self.student.id, self.organizer.id, self.other_organizer.id])
            ).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
        self.app_context.pop()

    def test_student_submit_query_and_organizer_notification(self):
        """Test student submitting an event query with auto-filled fields and notification generation."""
        # Login as student
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student.id
            sess['_user_id'] = str(self.student.id)

        # Submit query
        resp = self.client.post(
            f'/events/{self.event.id}/query',
            data={
                'query_text': 'What hardware components are allowed in this hackathon?'
            },
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        # Check confirmation message
        self.assertIn(b"Your query has been sent to the organizer.", resp.data)

        # Verify DB record
        query_record = EventQuery.query.filter_by(event_id=self.event.id, student_id=self.student.id).first()
        self.assertIsNotNone(query_record)
        self.assertEqual(query_record.student_name, self.student.name)
        self.assertEqual(query_record.student_roll_number, self.student_profile.roll_number)
        self.assertEqual(query_record.student_email, self.student.email)
        self.assertEqual(query_record.event_name, self.event.title)
        self.assertEqual(query_record.status, QueryStatus.PENDING)
        self.assertEqual(query_record.organizer_id, self.organizer.id)
        self.assertTrue(query_record.is_pending)

        # Verify organizer in-app notification
        notif = Notification.query.filter_by(
            user_id=self.organizer.id,
            type=NotificationType.STUDENT_QUERY
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn(self.event.title, notif.title)
        self.assertIn(self.student.name, notif.message)
        self.assertIn("What hardware components", notif.message)

    def test_student_views_queries_and_replies(self):
        """Test student viewing submitted queries and organizer replies on event page and my_queries."""
        # Create a pre-existing query with reply
        query_record = EventQuery(
            event_id=self.event.id,
            student_id=self.student.id,
            organizer_id=self.organizer.id,
            student_name=self.student.name,
            student_roll_number=self.student_profile.roll_number,
            student_email=self.student.email,
            event_name=self.event.title,
            query_text="Can we participate in a team of 3?",
            reply_text="Yes, teams of 2 to 4 members are allowed.",
            status=QueryStatus.REPLIED,
            created_at=datetime.utcnow(),
            replied_at=datetime.utcnow()
        )
        db.session.add(query_record)
        db.session.commit()

        # Login as student
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student.id
            sess['_user_id'] = str(self.student.id)

        # 1. View Event Detail page
        resp_event = self.client.get(f'/events/{self.event.slug}')
        self.assertEqual(resp_event.status_code, 200)
        self.assertIn(b"Can we participate in a team of 3?", resp_event.data)
        self.assertIn(b"Yes, teams of 2 to 4 members are allowed.", resp_event.data)
        self.assertIn(b"Replied", resp_event.data)

        # 2. View My Queries page
        resp_queries = self.client.get('/student/queries')
        self.assertEqual(resp_queries.status_code, 200)
        self.assertIn(b"Can we participate in a team of 3?", resp_queries.data)
        self.assertIn(b"Yes, teams of 2 to 4 members are allowed.", resp_queries.data)
        self.assertIn(b"Replied", resp_queries.data)

    def test_organizer_side_display_reply_and_close(self):
        """Test organizer viewing queries only for their events, replying, closing, and student notification."""
        # Create query for John's event
        john_query = EventQuery(
            event_id=self.event.id,
            student_id=self.student.id,
            organizer_id=self.organizer.id,
            student_name=self.student.name,
            student_roll_number=self.student_profile.roll_number,
            student_email=self.student.email,
            event_name=self.event.title,
            query_text="Is lunch provided at the event venue?",
            status=QueryStatus.PENDING,
            created_at=datetime.utcnow()
        )
        db.session.add(john_query)
        db.session.commit()

        # 1. Login as Other Organizer Alice - should NOT see John's event queries (Strict Isolation)
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.other_organizer.id
            sess['_user_id'] = str(self.other_organizer.id)

        resp_alice = self.client.get('/organizer/queries')
        self.assertEqual(resp_alice.status_code, 200)
        self.assertNotIn(b"Is lunch provided at the event venue?", resp_alice.data)

        # Alice cannot reply to John's query (403 Forbidden)
        resp_alice_reply = self.client.post(
            f'/organizer/queries/{john_query.id}/reply',
            data={'reply_text': 'Unauthorized reply'},
            follow_redirects=True
        )
        self.assertEqual(resp_alice_reply.status_code, 403)

        # 2. Login as Organizer John
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.organizer.id
            sess['_user_id'] = str(self.organizer.id)

        # View queries in Dashboard and Queries hub
        resp_dash = self.client.get('/organizer/dashboard')
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn(b"Student Queries", resp_dash.data)
        self.assertIn(b"Is lunch provided at the event venue?", resp_dash.data)

        resp_hub = self.client.get('/organizer/queries')
        self.assertEqual(resp_hub.status_code, 200)
        self.assertIn(self.student.name.encode(), resp_hub.data)
        self.assertIn(self.student_profile.roll_number.encode(), resp_hub.data)
        self.assertIn(self.student.email.encode(), resp_hub.data)
        self.assertIn(self.event.title.encode(), resp_hub.data)
        self.assertIn(b"Pending", resp_hub.data)

        # 3. Organizer John replies to student
        reply_msg = "Yes, lunch and refreshments will be provided."
        resp_reply = self.client.post(
            f'/organizer/queries/{john_query.id}/reply',
            data={'reply_text': reply_msg},
            follow_redirects=True
        )
        self.assertEqual(resp_reply.status_code, 200)

        # Verify DB updated
        db.session.refresh(john_query)
        self.assertEqual(john_query.status, QueryStatus.REPLIED)
        self.assertEqual(john_query.reply_text, reply_msg)
        self.assertIsNotNone(john_query.replied_at)

        # Verify Student received in-app notification
        student_notif = Notification.query.filter_by(
            user_id=self.student.id,
            type=NotificationType.QUERY_REPLY
        ).first()
        self.assertIsNotNone(student_notif)
        self.assertIn(self.event.title, student_notif.title)
        self.assertIn("Yes, lunch and refreshments", student_notif.message)

        # 4. Organizer John marks query as Closed
        resp_close = self.client.post(
            f'/organizer/queries/{john_query.id}/close',
            follow_redirects=True
        )
        self.assertEqual(resp_close.status_code, 200)

        db.session.refresh(john_query)
        self.assertEqual(john_query.status, QueryStatus.CLOSED)
        self.assertTrue(john_query.is_closed)
        self.assertIsNotNone(john_query.closed_at)


if __name__ == '__main__':
    unittest.main()
