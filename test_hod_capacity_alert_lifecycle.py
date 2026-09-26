"""
Campus Flow - Automated Test Suite for Updated HOD Notification Lifecycle
Validates:
1. Event starts with empty slots -> alert sent to responsible HOD with:
   - Event name
   - Number of empty slots
   - Event start time formatted in IST
   - Database stores event_id and expires_at based on event.end_time.
2. Alert remains visible only while event is active; once end_time passes (or expires_at <= IST now),
   it is automatically deleted from HOD notification panel.
3. Unrelated HOD notifications are NEVER deleted.
4. If event is cancelled, active empty-slot alert for that event is automatically removed.
5. If event date/time is edited, alert expiration time is recalculated using updated end_time.
6. Backend automated cleanup runs independently of page reload.
7. Cleanup executes upon HOD dashboard/notification view to eliminate stale database records.
8. Attendance records, registrations, and event data are completely unaffected.
9. Duplicate empty-slot alerts for the same event are strictly prevented.
"""
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import create_app
from models import (
    db, User, UserRole, CollegeDepartment, FacultyProfile, StudentProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    AttendanceRecord, AttendanceStatus, Notification, NotificationType, EventNotificationLog
)
from services.capacity_notification_service import (
    notify_hod_event_started,
    cleanup_expired_capacity_notifications,
    remove_event_capacity_alerts,
    update_event_capacity_alert_expiration,
    check_and_notify_empty_slots
)
from services.timezone_service import to_ist, get_current_ist_time, format_ist_datetime

IST = ZoneInfo("Asia/Kolkata")


class TestHODCapacityAlertLifecycle(unittest.TestCase):

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
                phone="+91 9888877777",
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

    def test_01_alert_content_and_database_behavior(self):
        """
        Verify:
        - Alert sent to respective HOD showing event name, empty slots count, and start time in IST.
        - event_id and expires_at are stored on the notification based on event.end_time.
        - Prevent duplicate alerts for the same event.
        """
        now = datetime.utcnow()
        organizer = self._get_or_create_user("org.lifecycle1@college.edu", "Organizer One", UserRole.ORGANIZER)
        hod_cse = self._get_or_create_user("hod.lifecycle.cse@college.edu", "Dr. CSE HOD", UserRole.HOD, "CSE")
        dept_cse = self._get_or_create_dept("CSE", "Computer Science & Engineering", hod_cse)

        start_time = now + timedelta(minutes=5)
        end_time = now + timedelta(hours=3)

        event = Event(
            title="AI/ML National Hackathon",
            slug=f"aiml-hackathon-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=dept_cse.id,
            max_participants=100,
            start_time=start_time,
            end_time=end_time,
            registration_deadline=start_time,
            venue="Tech Complex 101",
            description="24-hour hackathon",
            faculty_coordinator="Prof. Machine Learning",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.flush()

        # Register 60 confirmed students -> 40 empty slots
        for i in range(60):
            st = self._get_or_create_user(f"student_ml_{i}_{int(now.timestamp())}@college.edu", f"Student {i}", UserRole.STUDENT)
            reg = EventRegistration(
                event_id=event.id,
                student_id=st.id,
                registration_code=f"REG-AIML-{i}-{int(now.timestamp())}",
                status=RegistrationStatus.CONFIRMED
            )
            db.session.add(reg)
        db.session.commit()

        self.assertEqual(event.empty_slots, 40)

        # Trigger event started notification
        res = notify_hod_event_started(event)
        self.assertIsNotNone(res)
        self.assertEqual(res['empty_slots'], 40)

        # Retrieve created notification
        notif = Notification.query.filter_by(
            user_id=hod_cse.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()

        self.assertIsNotNone(notif)
        # 1. Event Name
        self.assertIn("AI/ML National Hackathon", notif.title)
        self.assertIn("AI/ML National Hackathon", notif.message)
        # 2. Number of empty slots
        self.assertIn("40 empty slots remaining", notif.message)
        # 3. Event start time in IST
        expected_ist_start = format_ist_datetime(start_time)
        self.assertIn(expected_ist_start, notif.message)
        # 4. Database references
        self.assertEqual(notif.event_id, event.id)
        self.assertLess(abs((notif.expires_at - end_time).total_seconds()), 2)
        self.assertFalse(notif.is_expired)

        # Prevent duplicate alert for the same event
        dup_res = notify_hod_event_started(event)
        self.assertIsNone(dup_res)
        alert_count = Notification.query.filter_by(
            user_id=hod_cse.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).count()
        self.assertEqual(alert_count, 1)

    def test_02_backend_auto_cleanup_when_event_end_time_passes(self):
        """
        Verify:
        - When event end time passes (expires_at <= current time),
          backend cleanup automatically removes the empty-slot alert.
        - Does NOT delete unrelated HOD notifications.
        - Does NOT affect attendance records or registrations.
        """
        now = datetime.utcnow()
        organizer = self._get_or_create_user("org.lifecycle2@college.edu", "Organizer Two", UserRole.ORGANIZER)
        hod_cse = self._get_or_create_user("hod.lifecycle.cse@college.edu", "Dr. CSE HOD", UserRole.HOD, "CSE")
        dept_cse = self._get_or_create_dept("CSE", "Computer Science & Engineering", hod_cse)

        # Create an unrelated notification for this HOD
        unrelated_notif = Notification(
            user_id=hod_cse.id,
            title="Faculty Meeting Agenda",
            message="Meeting scheduled for next Monday at 10 AM.",
            type=NotificationType.SYSTEM,
            is_read=False,
            created_at=now
        )
        db.session.add(unrelated_notif)

        # Create event that is now ending
        event = Event(
            title="Expired Workshop",
            slug=f"exp-workshop-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=dept_cse.id,
            max_participants=50,
            start_time=now - timedelta(hours=2),
            end_time=now + timedelta(hours=1), # initially 1 hr future
            registration_deadline=now - timedelta(hours=2),
            venue="Lab 1",
            description="Workshop",
            faculty_coordinator="Prof. Test",
            status=EventStatus.STARTED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(event)
        db.session.flush()

        student = self._get_or_create_user("stud.attendee@college.edu", "Attendee Student", UserRole.STUDENT)
        reg = EventRegistration(
            event_id=event.id,
            student_id=student.id,
            registration_code=f"REG-ATT-{int(now.timestamp())}",
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg)
        db.session.flush()

        att = AttendanceRecord(
            event_id=event.id,
            student_id=student.id,
            registration_id=reg.id,
            status=AttendanceStatus.PRESENT
        )
        db.session.add(att)
        db.session.commit()

        # Trigger notification
        notify_hod_event_started(event)
        alert = Notification.query.filter_by(
            user_id=hod_cse.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()
        self.assertIsNotNone(alert)

        # Now simulate time passing: event's end_time and alert's expires_at are in the past
        past_end_time = now - timedelta(minutes=5)
        event.end_time = past_end_time
        alert.expires_at = past_end_time
        db.session.commit()

        # Run backend automated cleanup
        removed = cleanup_expired_capacity_notifications()
        self.assertGreaterEqual(removed, 1)

        # Verify the expired capacity alert was removed from Notification table
        cleaned_alert = Notification.query.filter_by(
            user_id=hod_cse.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()
        self.assertIsNone(cleaned_alert)

        # Verify UNRELATED notification is completely intact
        persisted_unrelated = Notification.query.get(unrelated_notif.id)
        self.assertIsNotNone(persisted_unrelated)
        self.assertEqual(persisted_unrelated.title, "Faculty Meeting Agenda")

        # Verify attendance record and registration are completely intact
        persisted_reg = EventRegistration.query.filter_by(event_id=event.id, student_id=student.id).first()
        self.assertIsNotNone(persisted_reg)
        self.assertEqual(persisted_reg.status, RegistrationStatus.CONFIRMED)

        persisted_att = AttendanceRecord.query.filter_by(event_id=event.id, student_id=student.id).first()
        self.assertIsNotNone(persisted_att)
        self.assertEqual(persisted_att.status, AttendanceStatus.PRESENT)

    def test_03_cleanup_on_hod_page_open_and_api(self):
        """
        Verify:
        - When the HOD notification endpoint / page is opened, stale alerts are cleaned up
          immediately so they cannot remain visible.
        - Real-time POST /hod/notifications/cleanup-expired endpoint functions properly.
        """
        now = datetime.utcnow()
        hod_cse = self._get_or_create_user("hod.pageopen.cse@college.edu", "Dr. PageOpen HOD", UserRole.HOD, "CSE")
        dept_cse = self._get_or_create_dept("CSE", "Computer Science & Engineering", hod_cse)
        organizer = self._get_or_create_user("org.pageopen@college.edu", "Organizer Page", UserRole.ORGANIZER)

        event = Event(
            title="Stale Event Test",
            slug=f"stale-event-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=dept_cse.id,
            max_participants=30,
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1), # already ended
            registration_deadline=now - timedelta(hours=3),
            venue="Room 202",
            description="Stale event",
            faculty_coordinator="Prof. Test",
            status=EventStatus.STARTED,
            is_published=True,
            hod_approved=True,
            dean_approved=True
        )
        db.session.add(event)
        db.session.flush()

        # Insert a stale notification directly (simulating pre-existing stale record)
        stale_notif = Notification(
            user_id=hod_cse.id,
            title="🔔 Event Started: Stale Event Test",
            message="Event has empty slots.",
            type=NotificationType.EVENT_CAPACITY_ALERT,
            link=f"/events/{event.id}",
            event_id=event.id,
            expires_at=now - timedelta(minutes=10), # expired in past
            is_expired=False,
            is_read=False,
            created_at=now - timedelta(hours=2)
        )
        db.session.add(stale_notif)
        db.session.commit()

        # Call GET /hod/notifications
        with self.client.session_transaction() as sess:
            sess['user_id'] = hod_cse.id

        resp = self.client.get('/hod/notifications')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])

        # Verify stale capacity alert is NOT in the returned notifications list
        returned_notifs = data['notifications']
        stale_found = any(n['id'] == stale_notif.id for n in returned_notifs)
        self.assertFalse(stale_found)

        # Verify it was deleted from DB
        db_check = Notification.query.get(stale_notif.id)
        self.assertIsNone(db_check)

        # Test POST /hod/notifications/cleanup-expired
        post_resp = self.client.post('/hod/notifications/cleanup-expired')
        self.assertEqual(post_resp.status_code, 200)
        post_data = post_resp.get_json()
        self.assertTrue(post_data['success'])
        self.assertIn('removed_count', post_data)

    def test_04_event_cancellation_removes_active_alert(self):
        """
        Verify:
        - If an event is cancelled, the active empty-slot alert for that event
          is automatically removed.
        """
        now = datetime.utcnow()
        organizer = self._get_or_create_user("org.cancel@college.edu", "Organizer Cancel", UserRole.ORGANIZER)
        hod_cse = self._get_or_create_user("hod.cancel.cse@college.edu", "Dr. Cancel HOD", UserRole.HOD, "CSE")
        dept_cse = self._get_or_create_dept("CSE", "Computer Science & Engineering", hod_cse)

        event = Event(
            title="Cancelled Tech Talk",
            slug=f"cancel-talk-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=dept_cse.id,
            max_participants=50,
            start_time=now + timedelta(minutes=10),
            end_time=now + timedelta(hours=2),
            registration_deadline=now,
            venue="Seminar Hall",
            description="Talk to be cancelled",
            faculty_coordinator="Prof. Speaker",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.commit()

        # Trigger notification
        notify_hod_event_started(event)
        active_alert = Notification.query.filter_by(
            user_id=hod_cse.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()
        self.assertIsNotNone(active_alert)

        # Cancel event by setting status to CANCELLED (triggers SQLAlchemy status listener & helper)
        event.status = EventStatus.CANCELLED
        db.session.commit()

        # The active empty slot alert must be removed
        alert_after_cancel = Notification.query.filter_by(
            user_id=hod_cse.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()
        self.assertIsNone(alert_after_cancel)

    def test_05_event_date_time_edit_recalculates_alert_expiration(self):
        """
        Verify:
        - If the event time/date is edited, the alert expiration time (expires_at)
          is recalculated using the updated event end time.
        - If updated end time is in the past, alert is removed immediately.
        """
        now = datetime.utcnow()
        organizer = self._get_or_create_user("org.edit@college.edu", "Organizer Edit", UserRole.ORGANIZER)
        hod_cse = self._get_or_create_user("hod.edit.cse@college.edu", "Dr. Edit HOD", UserRole.HOD, "CSE")
        dept_cse = self._get_or_create_dept("CSE", "Computer Science & Engineering", hod_cse)

        initial_end = now + timedelta(hours=2)
        event = Event(
            title="Rescheduled Webinar",
            slug=f"resched-webinar-{int(now.timestamp())}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=dept_cse.id,
            max_participants=40,
            start_time=now + timedelta(minutes=15),
            end_time=initial_end,
            registration_deadline=now,
            venue="Online",
            description="Webinar",
            faculty_coordinator="Prof. Speaker",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.commit()

        # Trigger notification
        notify_hod_event_started(event)
        alert = Notification.query.filter_by(
            user_id=hod_cse.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()
        self.assertIsNotNone(alert)
        self.assertLess(abs((alert.expires_at - initial_end).total_seconds()), 2)

        # Organizer extends event end time by 3 additional hours
        new_end_time = now + timedelta(hours=5)
        event.end_time = new_end_time
        db.session.commit()

        update_count = update_event_capacity_alert_expiration(event)
        self.assertEqual(update_count, 1)

        # Verify alert expires_at was updated to new end time
        updated_alert = Notification.query.get(alert.id)
        self.assertIsNotNone(updated_alert)
        self.assertLess(abs((updated_alert.expires_at - new_end_time).total_seconds()), 2)

        # Now simulate editing event end_time to past -> should purge alert immediately
        past_end = now - timedelta(minutes=10)
        event.end_time = past_end
        db.session.commit()

        update_event_capacity_alert_expiration(event)
        purged_alert = Notification.query.get(alert.id)
        self.assertIsNone(purged_alert)


if __name__ == '__main__':
    unittest.main()
