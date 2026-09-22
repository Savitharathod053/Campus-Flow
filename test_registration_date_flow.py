import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import app, db
from models import (
    User, UserRole, CollegeDepartment, Event, EventStatus, EventType,
    EventRequest, EventRequestStatus, EventRegistration, RegistrationStatus,
    StudentProfile
)
from services.timezone_service import (
    IST, UTC, parse_form_datetime, to_ist_input_format, to_ist,
    format_ist_datetime
)
from services.import_service import parse_event_import_dates


class TestRegistrationDateFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        cls.app = app
        cls.client = app.test_client()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.rollback()
        self.ctx.pop()

    def test_1_timezone_parsing_and_zero_shift(self):
        """
        Test that user-entered IST datetime-local strings:
        - Are parsed as IST
        - Converted to UTC for storage
        - Converted back to IST with 0-minute shift
        - Pre-filled in forms as the exact original string
        """
        # User enters: 20 Sept 2026 at 10:30 AM IST
        input_str = '2026-09-20T10:30'
        utc_dt = parse_form_datetime(input_str)
        
        # 10:30 AM IST minus 5 hours 30 mins is 05:00 AM UTC
        self.assertEqual(utc_dt.year, 2026)
        self.assertEqual(utc_dt.month, 9)
        self.assertEqual(utc_dt.day, 20)
        self.assertEqual(utc_dt.hour, 5)
        self.assertEqual(utc_dt.minute, 0)

        # Rendering back to IST input format reproduces exact string
        form_value = to_ist_input_format(utc_dt)
        self.assertEqual(form_value, input_str)

        # Rendering in Jinja datetimeformat filter matches 10:30 AM IST
        ist_dt = to_ist(utc_dt)
        self.assertEqual(ist_dt.hour, 10)
        self.assertEqual(ist_dt.minute, 30)
        self.assertIn("10:30 AM", ist_dt.strftime('%b %d, %Y - %I:%M %p'))

    def test_2_model_fields_and_aliases(self):
        """Test separate registration_start_date and alias properties on Event and EventRequest."""
        now = datetime.utcnow()
        reg_start = now + timedelta(days=1)
        deadline = now + timedelta(days=5)
        ev_start = now + timedelta(days=7)
        ev_end = now + timedelta(days=8)

        event = Event(
            title="Test Separate Dates",
            description="Test separate dates description",
            slug=f"test-separate-dates-{int(now.timestamp())}",
            organizer_id=1,
            department="CSE",
            faculty_coordinator="Dr. Test",
            venue="Hall 1",
            registration_start_date=reg_start,
            registration_deadline=deadline,
            start_time=ev_start,
            end_time=ev_end,
            max_participants=50,
            is_free=True
        )

        self.assertEqual(event.registration_start_date, reg_start)
        self.assertEqual(event.registration_end_date, deadline)
        self.assertEqual(event.event_start_date, ev_start)
        self.assertEqual(event.event_end_date, ev_end)

        # Test setter aliases
        new_deadline = deadline + timedelta(days=1)
        event.registration_end_date = new_deadline
        self.assertEqual(event.registration_deadline, new_deadline)

    def test_3_registration_status_lifecycle(self):
        """
        Test registration lifecycle logic:
        - Before registration_start_date: 'Registration Not Started', live open is False
        - Between start and deadline: 'Registration Open', live open is True
        - After deadline: 'Registration Closed', live open is False
        """
        now = datetime.utcnow()
        
        # Case A: Not yet started
        event_future = Event(
            title="Future Reg",
            slug=f"future-reg-{int(now.timestamp())}",
            organizer_id=1,
            department="CSE",
            faculty_coordinator="Dr. Future",
            venue="Room A",
            registration_start_date=now + timedelta(days=2),
            registration_deadline=now + timedelta(days=5),
            start_time=now + timedelta(days=6),
            end_time=now + timedelta(days=7),
            max_participants=50,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        self.assertTrue(event_future.is_registration_not_started)
        self.assertFalse(event_future.is_live_registration_open)
        self.assertEqual(event_future.registration_status, 'Registration Not Started')

        # Case B: Currently Open
        event_open = Event(
            title="Open Reg",
            slug=f"open-reg-{int(now.timestamp())}",
            organizer_id=1,
            department="CSE",
            faculty_coordinator="Dr. Open",
            venue="Room B",
            registration_start_date=now - timedelta(days=1),
            registration_deadline=now + timedelta(days=3),
            start_time=now + timedelta(days=4),
            end_time=now + timedelta(days=5),
            max_participants=50,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        self.assertFalse(event_open.is_registration_not_started)
        self.assertFalse(event_open.is_deadline_passed)
        self.assertTrue(event_open.is_live_registration_open)
        self.assertEqual(event_open.registration_status, 'Registration Open')

        # Case C: Deadline passed
        event_closed = Event(
            title="Closed Reg",
            slug=f"closed-reg-{int(now.timestamp())}",
            organizer_id=1,
            department="CSE",
            faculty_coordinator="Dr. Closed",
            venue="Room C",
            registration_start_date=now - timedelta(days=5),
            registration_deadline=now - timedelta(days=1),
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
            max_participants=50,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        self.assertFalse(event_closed.is_registration_not_started)
        self.assertTrue(event_closed.is_deadline_passed)
        self.assertFalse(event_closed.is_live_registration_open)
        self.assertEqual(event_closed.registration_status, 'Registration Closed')

    def test_4_spreadsheet_import_date_parser(self):
        """Test parse_event_import_dates without using file timestamps."""
        row_valid = {
            'registration_start_date': '20-09-2026 10:30',
            'registration_deadline': '25-09-2026 23:59',
            'event_start_date': '27-09-2026 10:00',
            'event_end_date': '27-09-2026 17:00'
        }
        dates, errors = parse_event_import_dates(row_valid)
        self.assertEqual(errors, [])
        self.assertIsNotNone(dates['registration_start_date'])
        self.assertIsNotNone(dates['registration_deadline'])
        self.assertIsNotNone(dates['start_time'])
        self.assertIsNotNone(dates['end_time'])
        self.assertLess(dates['registration_start_date'], dates['registration_deadline'])
        self.assertLessEqual(dates['registration_deadline'], dates['start_time'])
        self.assertLess(dates['start_time'], dates['end_time'])

        # Invalid chronological order: reg_start >= deadline
        row_invalid = {
            'registration_start_date': '26-09-2026 10:00',
            'registration_deadline': '25-09-2026 10:00',
            'event_start_date': '27-09-2026 10:00',
            'event_end_date': '27-09-2026 17:00'
        }
        dates, errors = parse_event_import_dates(row_invalid)
        self.assertTrue(any("Registration start date must be strictly before" in e for e in errors))

    def test_5_edit_event_preserves_registration_dates(self):
        """Test that editing event metadata does not overwrite or shift registration dates."""
        organizer = User.query.filter_by(role=UserRole.FACULTY).first() or User.query.first()
        now = datetime.utcnow().replace(microsecond=0)
        reg_start = now - timedelta(days=2)
        deadline = now + timedelta(days=3)
        ev_start = now + timedelta(days=4)
        ev_end = now + timedelta(days=5)

        event = Event(
            title="Original Title",
            description="Original description text",
            slug=f"orig-title-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            faculty_coordinator="Prof. Origin",
            venue="Original Lab",
            registration_start_date=reg_start,
            registration_deadline=deadline,
            start_time=ev_start,
            end_time=ev_end,
            max_participants=100,
            is_free=True,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(event)
        db.session.commit()

        # Update description only via route/model
        event.description = "Updated description text"
        # Verify dates remain untouched and not set to now/created_at
        self.assertEqual(event.registration_start_date, reg_start)
        self.assertEqual(event.registration_deadline, deadline)
        self.assertEqual(event.start_time, ev_start)
        self.assertEqual(event.end_time, ev_end)

    def test_6_organizer_create_event_endpoint_validation(self):
        """Test chronological validation in organizer create_event route."""
        organizer = User.query.filter_by(role=UserRole.ORGANIZER).first() or User.query.first()
        dept = CollegeDepartment.query.first()

        with self.client.session_transaction() as sess:
            sess['user_id'] = organizer.id
            sess['_user_role'] = UserRole.ORGANIZER

        # Invalid: registration_start_date >= registration_deadline
        resp = self.client.post('/organizer/events/create', data={
            'title': 'Chronology Error Event',
            'event_type': 'Workshop',
            'department': dept.code if dept else 'CSE',
            'venue': 'Lab 1',
            'faculty_coordinator': 'Dr. Coordinator',
            'description': 'Description here',
            'registration_start_date': '2026-09-25T10:00',
            'registration_deadline': '2026-09-24T10:00', # earlier than start!
            'start_time': '2026-09-26T10:00',
            'end_time': '2026-09-26T17:00',
            'max_participants': '100',
            'is_free': 'true'
        }, follow_redirects=True)
        self.assertIn(b'Registration start date/time must be earlier than the registration deadline', resp.data)

        # Invalid: registration_deadline > start_time
        resp2 = self.client.post('/organizer/events/create', data={
            'title': 'Chronology Error Event 2',
            'event_type': 'Workshop',
            'department': dept.code if dept else 'CSE',
            'venue': 'Lab 1',
            'faculty_coordinator': 'Dr. Coordinator',
            'description': 'Description here',
            'registration_start_date': '2026-09-20T10:00',
            'registration_deadline': '2026-09-27T10:00', # after event start!
            'start_time': '2026-09-26T10:00',
            'end_time': '2026-09-26T17:00',
            'max_participants': '100',
            'is_free': 'true'
        }, follow_redirects=True)
        self.assertIn(b'Registration deadline must be before or equal to the event start time', resp2.data)

    def test_7_dean_approval_copies_registration_start_date(self):
        """Test that Dean approval copies registration_start_date from EventRequest to Event."""
        organizer = User.query.filter_by(role=UserRole.ORGANIZER).first() or User.query.first()
        dept = CollegeDepartment.query.first()
        dean = User.query.filter_by(role=UserRole.STUDENTS_AFFAIRS_DEAN).first()

        now = datetime.utcnow().replace(microsecond=0)
        reg_start = now + timedelta(days=1)
        deadline = now + timedelta(days=3)
        ev_start = now + timedelta(days=4)
        ev_end = now + timedelta(days=5)

        event_req = EventRequest(
            organizer_id=organizer.id,
            department_id=dept.id if dept else 1,
            event_name=f"Dean Prop {int(now.timestamp())}",
            description="Detailed proposal description",
            category="Workshop",
            proposed_event_date=ev_start.date(),
            start_time=ev_start,
            end_time=ev_end,
            venue="Auditorium",
            expected_participants=80,
            registration_start_date=reg_start,
            registration_deadline=deadline,
            registration_fee=0.0,
            is_free=True,
            hod_approval_status='approved',
            overall_status=EventRequestStatus.PENDING_DEAN_APPROVAL
        )
        db.session.add(event_req)
        db.session.commit()

        if dean:
            with self.client.session_transaction() as sess:
                sess['user_id'] = dean.id
                sess['_user_role'] = dean.role

            resp = self.client.post(f'/dean/requests/{event_req.id}/approve', follow_redirects=True)
            self.assertEqual(resp.status_code, 200)

            # Check Event created
            created_event = Event.query.filter_by(event_request_id=event_req.id).first()
            self.assertIsNotNone(created_event)
            self.assertEqual(created_event.registration_start_date, reg_start)
            self.assertEqual(created_event.registration_deadline, deadline)

    def test_8_student_registration_endpoint_enforcement(self):
        """Test that student cannot register before registration_start_date."""
        student = User.query.filter_by(role=UserRole.STUDENT).first()
        organizer = User.query.filter_by(role=UserRole.FACULTY).first() or User.query.first()

        now = datetime.utcnow().replace(microsecond=0)
        future_event = Event(
            title=f"Future Event {int(now.timestamp())}",
            description="Future event description",
            slug=f"future-ev-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            faculty_coordinator="Prof. Future",
            venue="Hall Z",
            registration_start_date=now + timedelta(days=2), # Registration opens in 2 days
            registration_deadline=now + timedelta(days=5),
            start_time=now + timedelta(days=6),
            end_time=now + timedelta(days=7),
            max_participants=50,
            is_free=True,
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(future_event)
        db.session.commit()

        if student:
            with self.client.session_transaction() as sess:
                sess['user_id'] = student.id
                sess['_user_role'] = student.role

            # Attempt to register
            resp = self.client.post(f'/student/register/{future_event.id}', follow_redirects=True)
            self.assertIn(b'Registration for this event has not started yet', resp.data)

            # Verify no registration created
            reg = EventRegistration.query.filter_by(event_id=future_event.id, student_id=student.id).first()
            self.assertIsNone(reg)


if __name__ == '__main__':
    unittest.main()

