import sys
import unittest
from datetime import datetime, timedelta
from app import create_app, db
from models import (
    User, StudentProfile, OrganizerProfile, Event, EventStatus, EventType,
    EventRegistration, RegistrationStatus, Notification, NotificationType,
    CustomRegistrationField, CustomFieldResponse, Payment, PaymentStatus
)
from services.capacity_notification_service import notify_hod_spot_registration_closed
from services.email_service import SENT_EMAILS

class SpotRegistrationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        SENT_EMAILS.clear()

        # Unique suffix for test isolation
        ts = int(datetime.utcnow().timestamp() * 1000)
        self.suffix = f"spot_{ts}"

        # Create HOD user
        self.hod = User(
            name=f"Dr. CSE HOD {self.suffix}",
            email=f"hod_{self.suffix}@campusflow.edu",
            phone="9988776655",
            role="hod",
            is_active=True
        )
        self.hod.set_password("HodPass@123")
        db.session.add(self.hod)

        # Create Organizer user
        self.organizer = User(
            name=f"Organizer {self.suffix}",
            email=f"org_{self.suffix}@campusflow.edu",
            phone="9988776654",
            role="organizer",
            is_active=True
        )
        self.organizer.set_password("OrgPass@123")
        db.session.add(self.organizer)
        db.session.flush()

        self.org_profile = OrganizerProfile(
            user_id=self.organizer.id,
            organization_name="Tech Club",
            department="CSE"
        )
        db.session.add(self.org_profile)

        # Create an approved Event
        self.event = Event(
            title=f"National Hackathon {self.suffix}",
            slug=f"hackathon-{self.suffix}",
            description="Testing spot registration system",
            organizer_id=self.organizer.id,
            department="CSE",
            event_type=EventType.WORKSHOP,
            venue="Tech Auditorium",
            faculty_coordinator="Prof. Test Coordinator",
            faculty_coordinator_contact="9876543210",
            start_time=datetime.utcnow() + timedelta(days=1),
            end_time=datetime.utcnow() + timedelta(days=2),
            registration_deadline=datetime.utcnow() - timedelta(hours=1),
            max_participants=50,
            spot_registration_slots=5,
            spot_registration_closed=False,
            is_free=False,
            registration_fee=150.0,
            responsible_hod_id=self.hod.id,
            status=EventStatus.APPROVED
        )
        db.session.add(self.event)
        db.session.flush()

        # Add custom field
        self.cf = CustomRegistrationField(
            event_id=self.event.id,
            field_name="tshirt_size",
            field_label="T-Shirt Size",
            field_type="select",
            options_csv="S,M,L,XL",
            is_required=False
        )
        db.session.add(self.cf)
        db.session.commit()

    def tearDown(self):
        try:
            # Clean up test entities
            db.session.rollback()
            CustomFieldResponse.query.filter(CustomFieldResponse.field_id == self.cf.id).delete()
            CustomRegistrationField.query.filter_by(event_id=self.event.id).delete()
            Payment.query.filter_by(event_id=self.event.id).delete()
            EventRegistration.query.filter_by(event_id=self.event.id).delete()
            Notification.query.filter_by(event_id=self.event.id).delete()
            db.session.delete(self.event)
            if self.org_profile:
                db.session.delete(self.org_profile)
            db.session.delete(self.organizer)
            db.session.delete(self.hod)
            db.session.commit()
        except Exception:
            db.session.rollback()
        self.app_context.pop()

    def _login(self, user):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user.id
            sess['_user_role'] = user.role

    def test_spot_registration_full_flow(self):
        """Test complete lifecycle: slots setup -> spot registration -> edit -> close -> HOD alert -> reopen"""
        self._login(self.organizer)

        # 1. Update spot slots
        resp = self.client.post(f'/organizer/events/{self.event.id}/spot-slots', data={
            'spot_registration_slots': 3
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.event = Event.query.get(self.event.id)
        self.assertEqual(self.event.spot_registration_slots, 3)

        # 2. Add Spot Student #1
        student1_roll = f"21CS{self.suffix[-4:]}1"
        student1_email = f"walkin1_{self.suffix}@campusflow.edu"
        resp = self.client.post(f'/organizer/events/{self.event.id}/spot-registration/add', data={
            'student_name': 'Walkin Student One',
            'roll_number': student1_roll,
            'email': student1_email,
            'phone': '9876543210',
            'department': 'CSE',
            'year': '3',
            'section': 'B',
            'payment_status': 'VERIFIED',
            f'custom_field_{self.cf.id}': 'L'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Verify Student, Registration, Payment, and Custom Field
        st1_user = User.query.filter_by(email=student1_email).first()
        self.assertIsNotNone(st1_user)
        self.assertEqual(st1_user.student_profile.roll_number, student1_roll)

        reg1 = EventRegistration.query.filter_by(event_id=self.event.id, student_id=st1_user.id).first()
        self.assertIsNotNone(reg1)
        self.assertEqual(reg1.registration_type, 'SPOT')
        self.assertEqual(reg1.status, RegistrationStatus.CONFIRMED)
        self.assertIsNotNone(reg1.qr_code_image)

        # Verify payment
        pay1 = Payment.query.filter_by(registration_id=reg1.id).first()
        self.assertIsNotNone(pay1)
        self.assertEqual(pay1.status, PaymentStatus.VERIFIED)
        self.assertEqual(pay1.amount, 150.0)

        # Verify custom answer
        cf_resp = CustomFieldResponse.query.filter_by(registration_id=reg1.id, field_id=self.cf.id).first()
        self.assertIsNotNone(cf_resp)
        self.assertEqual(cf_resp.field_value, 'L')

        # Check spot count
        self.assertEqual(self.event.spot_registrations_count, 1)
        self.assertEqual(self.event.spot_slots_remaining, 2)

        # 3. Add Spot Student #2
        student2_roll = f"21CS{self.suffix[-4:]}2"
        student2_email = f"walkin2_{self.suffix}@campusflow.edu"
        self.client.post(f'/organizer/events/{self.event.id}/spot-registration/add', data={
            'student_name': 'Walkin Student Two',
            'roll_number': student2_roll,
            'email': student2_email,
            'phone': '9876543211',
            'department': 'CSE',
            'year': '4',
            'section': 'A',
            'payment_status': 'VERIFIED'
        }, follow_redirects=True)

        self.assertEqual(self.event.spot_registrations_count, 2)
        self.assertEqual(self.event.spot_slots_remaining, 1)

        # 4. Edit Spot Student #1
        resp = self.client.post(f'/organizer/events/{self.event.id}/spot-registration/{reg1.id}/edit', data={
            'student_name': 'Walkin Student One Updated',
            'roll_number': student1_roll,
            'email': student1_email,
            'phone': '9876500000',
            'department': 'CSE',
            'year': '4',
            'section': 'C',
            'payment_status': 'VERIFIED',
            f'custom_field_{self.cf.id}': 'XL'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        st1_user = User.query.filter_by(email=student1_email).first()
        self.assertEqual(st1_user.name, 'Walkin Student One Updated')
        self.assertEqual(st1_user.student_profile.year, 4)
        self.assertEqual(st1_user.student_profile.section, 'C')
        cf_resp = CustomFieldResponse.query.filter_by(registration_id=reg1.id, field_id=self.cf.id).first()
        self.assertEqual(cf_resp.field_value, 'XL')

        # 5. Close Spot Registration with 1 unused slot (Total slots=3, Registered=2, Unused=1)
        resp = self.client.post(f'/organizer/events/{self.event.id}/spot-registration/close', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.event = Event.query.get(self.event.id)
        self.assertTrue(self.event.spot_registration_closed)
        self.assertTrue(self.event.spot_empty_slot_notification_sent)

        # Verify HOD In-App Notification was generated
        hod_notif = Notification.query.filter_by(
            user_id=self.hod.id,
            event_id=self.event.id,
            type=NotificationType.SPOT_CAPACITY_ALERT
        ).first()
        self.assertIsNotNone(hod_notif)
        self.assertIn("1 Unused Slots", hod_notif.title)
        self.assertIn("1 spot-registration slots remained unused", hod_notif.message)

        # Verify HOD Email record
        spot_emails = [e for e in SENT_EMAILS if e.get('type') == 'SPOT_CAPACITY_ALERT' and e.get('to') == self.hod.email]
        self.assertEqual(len(spot_emails), 1)
        self.assertIn("1 Unused Slots", spot_emails[0]['subject'])

        # 6. Duplicate prevention: Trying to close again or trigger notification again does NOT duplicate
        notif_result = notify_hod_spot_registration_closed(self.event)
        self.assertIsNone(notif_result)
        count_notifs = Notification.query.filter_by(
            user_id=self.hod.id,
            event_id=self.event.id,
            type=NotificationType.SPOT_CAPACITY_ALERT
        ).count()
        self.assertEqual(count_notifs, 1)

        # 7. Reopen Spot Registration
        resp = self.client.post(f'/organizer/events/{self.event.id}/spot-registration/reopen', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.event = Event.query.get(self.event.id)
        self.assertFalse(self.event.spot_registration_closed)

        # 8. Check Participants Filter
        resp = self.client.get(f'/organizer/events/{self.event.id}/participants?type=SPOT')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Walkin Student One Updated', resp.data)
        self.assertIn(b'Walkin Student Two', resp.data)

        # Clean up created students
        st2_user = User.query.filter_by(email=student2_email).first()
        reg2 = EventRegistration.query.filter_by(event_id=self.event.id, student_id=st2_user.id).first()
        Payment.query.filter_by(registration_id=reg2.id).delete()
        db.session.delete(reg2)
        db.session.delete(st2_user.student_profile)
        db.session.delete(st2_user)

        db.session.delete(st1_user.student_profile)
        db.session.delete(st1_user)
        db.session.commit()

    def test_spot_registration_zero_unused_no_hod_alert(self):
        """When all spot slots are filled, closing spot registration should NOT notify HOD."""
        self._login(self.organizer)

        # Set 1 slot
        self.client.post(f'/organizer/events/{self.event.id}/spot-slots', data={
            'spot_registration_slots': 1
        }, follow_redirects=True)

        # Register 1 student (fill 100%)
        student_roll = f"21CS{self.suffix[-4:]}9"
        student_email = f"full_{self.suffix}@campusflow.edu"
        self.client.post(f'/organizer/events/{self.event.id}/spot-registration/add', data={
            'student_name': 'Full Capacity Student',
            'roll_number': student_roll,
            'email': student_email,
            'department': 'CSE',
            'year': '2',
            'section': 'A'
        }, follow_redirects=True)

        SENT_EMAILS.clear()

        # Close spot registration
        resp = self.client.post(f'/organizer/events/{self.event.id}/spot-registration/close', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        # Notification should NOT be created for HOD because unused == 0
        hod_notif = Notification.query.filter_by(
            user_id=self.hod.id,
            event_id=self.event.id,
            type=NotificationType.SPOT_CAPACITY_ALERT
        ).first()
        self.assertIsNone(hod_notif)

        spot_emails = [e for e in SENT_EMAILS if e.get('type') == 'SPOT_CAPACITY_ALERT']
        self.assertEqual(len(spot_emails), 0)

        # Clean up
        u = User.query.filter_by(email=student_email).first()
        r = EventRegistration.query.filter_by(event_id=self.event.id, student_id=u.id).first()
        db.session.delete(r)
        db.session.delete(u.student_profile)
        db.session.delete(u)
        db.session.commit()

if __name__ == '__main__':
    unittest.main()
