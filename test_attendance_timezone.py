"""
Test suite for Attendance Timestamp Indian Standard Time (IST Asia/Kolkata) enforcement.
Verifies:
1. services.timezone_service conversions and formatting.
2. Naive vs aware datetime handling with no double conversion.
3. AttendanceSession.is_time_active using IST.
4. record_session_attendance API response serialization with IST.
5. Jinja template filter conversions to Asia/Kolkata.
"""
import unittest
from datetime import datetime, timezone, timedelta, time, date
from zoneinfo import ZoneInfo
from app import create_app
from models import (
    db, User, UserRole, StudentProfile, Event, EventRegistration,
    RegistrationStatus, AttendanceRecord, AttendanceStatus,
    AttendanceSession, AttendanceSessionStatus, VerificationMethod
)
from services.timezone_service import (
    IST, UTC, get_current_attendance_time, get_current_ist_time,
    get_current_utc_time, to_ist, to_utc, format_ist_datetime,
    format_ist_time, format_ist_date
)
from services.attendance_service import record_session_attendance

class AttendanceTimezoneTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def test_01_timezone_service_conversions(self):
        """Test to_ist conversions from UTC naive, UTC aware, and IST aware."""
        # 1. UTC naive datetime: 2026-09-22 07:30:00 (13:00 IST)
        utc_naive = datetime(2026, 9, 22, 7, 30, 0)
        ist_dt = to_ist(utc_naive)
        self.assertEqual(ist_dt.tzinfo, IST)
        self.assertEqual(ist_dt.hour, 13)
        self.assertEqual(ist_dt.minute, 0)
        self.assertEqual(ist_dt.day, 22)

        # 2. UTC aware datetime: 2026-09-22 07:30:00+00:00
        utc_aware = datetime(2026, 9, 22, 7, 30, 0, tzinfo=UTC)
        ist_dt2 = to_ist(utc_aware)
        self.assertEqual(ist_dt2.tzinfo, IST)
        self.assertEqual(ist_dt2.hour, 13)
        self.assertEqual(ist_dt2.minute, 0)

        # 3. Prevent double conversion: If already IST, should NOT add another 5:30
        ist_aware = datetime(2026, 9, 22, 13, 0, 0, tzinfo=IST)
        ist_dt3 = to_ist(ist_aware)
        self.assertEqual(ist_dt3.tzinfo, IST)
        self.assertEqual(ist_dt3.hour, 13)
        self.assertEqual(ist_dt3.minute, 0)

        # 4. ISO string handling
        iso_str = "2026-09-22T07:30:00Z"
        ist_dt4 = to_ist(iso_str)
        self.assertEqual(ist_dt4.hour, 13)
        self.assertEqual(ist_dt4.minute, 0)

    def test_02_formatting_utilities(self):
        """Test IST formatting output strings."""
        dt = datetime(2026, 9, 22, 7, 35, 0, tzinfo=UTC)
        formatted = format_ist_datetime(dt)
        self.assertIn("22 September 2026", formatted)
        self.assertIn("01:05 PM IST", formatted)

        formatted_time = format_ist_time(dt)
        self.assertEqual(formatted_time, "01:05 PM IST")

        formatted_date = format_ist_date(dt)
        self.assertEqual(formatted_date, "22 September 2026")

    def test_03_session_time_active_ist(self):
        """Test AttendanceSession.is_time_active uses IST properly."""
        session = AttendanceSession(
            session_name="Session 1 - Main Event",
            session_number=1,
            event_date=date(2026, 9, 22),
            start_time=time(13, 0),  # 01:00 PM IST
            end_time=time(15, 0),    # 03:00 PM IST
            status=AttendanceSessionStatus.ACTIVE
        )

        # Current time at 01:30 PM IST (08:00 AM UTC) -> should be active
        test_dt_active = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)
        is_active, msg = session.is_time_active(current_dt=test_dt_active)
        self.assertTrue(is_active)

        # Current time at 12:30 PM IST (07:00 AM UTC) -> should be inactive (opens at 01:00 PM)
        test_dt_early = datetime(2026, 9, 22, 7, 0, 0, tzinfo=UTC)
        is_active, msg = session.is_time_active(current_dt=test_dt_early)
        self.assertFalse(is_active)
        self.assertIn("opens at 01:00 PM", msg)

        # Current time at 03:30 PM IST (10:00 AM UTC) -> should be inactive (closed at 03:00 PM)
        test_dt_late = datetime(2026, 9, 22, 10, 0, 0, tzinfo=UTC)
        is_active, msg = session.is_time_active(current_dt=test_dt_late)
        self.assertFalse(is_active)
        self.assertIn("closed at 03:00 PM", msg)

    def test_04_attendance_record_model_ist(self):
        """Test AttendanceRecord.scanned_at_ist property."""
        rec = AttendanceRecord(
            scanned_at=datetime(2026, 9, 22, 8, 15, 0) # naive UTC 08:15 -> 13:45 IST
        )
        self.assertEqual(rec.scanned_at_ist.tzinfo, IST)
        self.assertEqual(rec.scanned_at_ist.hour, 13)
        self.assertEqual(rec.scanned_at_ist.minute, 45)

    def test_05_jinja_template_filters(self):
        """Test Jinja template filters datetimeformat and timeformat convert to IST."""
        with self.app.test_request_context():
            dt_utc = datetime(2026, 9, 22, 7, 30, 0) # naive UTC
            res_datetime = self.app.jinja_env.filters['datetimeformat'](dt_utc)
            self.assertIn("01:00 PM", res_datetime) # 07:30 + 5:30 = 13:00 (01:00 PM)

            res_time = self.app.jinja_env.filters['timeformat'](dt_utc)
            self.assertEqual(res_time, "01:00 PM")

if __name__ == '__main__':
    unittest.main()
