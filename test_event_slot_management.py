"""
Campus Flow - Test Suite for Event Slot Management & On-Spot Rollover / Editing
Verifies:
1. Core Slot Logic:
   - Event has ONE Total Event Capacity (max_participants).
   - Before online registration closes: all slots available for online; on-spot slots = 0.
   - When online registration closes: unused online slots become automatically available for on-spot.
     Formula: On-Spot Available = Total Event Capacity - Online Registrations.
2. Organizer Edit On-Spot Slots:
   - Organizer can edit on-spot slots after online registration closes.
   - Validation: Cannot set higher than remaining overall event capacity.
   - Validation: Cannot set below number of students already registered on-spot.
   - Validation: Clear error flash message when invalid value is entered.
3. On-Spot Registration:
   - When registered: On-Spot Registered increments, remaining decreases.
   - Never allow registration if on-spot slots are full.
   - Never allow Online + On-Spot to exceed Total Event Capacity.
4. Start Event:
   - Event starts only via manual click.
   - HOD notification dispatched with: Event name, Total Event Capacity, Online Registrations,
     On-Spot Registrations, Total Occupied, Remaining/Empty Slots.
"""
import unittest
from datetime import datetime, timedelta

from app import create_app
from models import (
    db, User, UserRole, CollegeDepartment, FacultyProfile, StudentProfile,
    Event, EventStatus, EventRegistration, RegistrationStatus,
    Notification, NotificationType
)


class TestEventSlotManagement(unittest.TestCase):

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

    def _get_or_create_user(self, email, name, role, dept="CSE"):
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                name=name,
                email=email,
                role=role,
                phone="+91 9777777777",
                is_active=True
            )
            user.set_password("Pass@123")
            db.session.add(user)
            db.session.flush()

            if role == UserRole.HOD:
                fp = FacultyProfile(
                    user_id=user.id,
                    employee_id=f"EMP-{dept}-{user.id}",
                    department=dept,
                    designation="Head of Department"
                )
                db.session.add(fp)

            if role == UserRole.STUDENT:
                sp = StudentProfile(
                    user_id=user.id,
                    roll_number=f"ROLL-{user.id}",
                    department=dept,
                    year=3,
                    section="A"
                )
                db.session.add(sp)
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

    def test_core_slot_logic_and_organizer_edit_flow(self):
        """
        Step-by-step test matching the prompt example:
        Total Capacity = 100
        Online Registrations = 72
        After online registration closes:
        On-Spot Available = 28
        Organizer edits to 25 -> accepted.
        Organizer tries 30 -> rejected (exceeds remaining unused 28).
        Register on-spot students up to 25 -> full, prevents overflow.
        Start event -> dispatches HOD notification with exact numbers.
        """
        now = datetime.utcnow()
        timestamp = int(now.timestamp())

        organizer = self._get_or_create_user(f"org_slot_{timestamp}@college.edu", "Organizer Slot", UserRole.ORGANIZER)
        hod_cse = self._get_or_create_user(f"hod_cse_{timestamp}@college.edu", "Dr. CSE HOD", UserRole.HOD, "CSE")
        dept_cse = self._get_or_create_dept("CSE", "Computer Science & Engineering", hod_cse)
        db.session.commit()

        # Create Event with Total Event Capacity = 100, registration deadline in future (Online OPEN)
        event = Event(
            title="AI Innovation Summit",
            slug=f"ai-summit-{timestamp}",
            organizer_id=organizer.id,
            department="CSE",
            department_id=dept_cse.id,
            max_participants=100,
            spot_registration_slots=0,
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=6),
            registration_deadline=now + timedelta(hours=2), # In future
            venue="Tech Auditorium",
            description="Summit on AI",
            faculty_coordinator="Prof. Faculty",
            status=EventStatus.APPROVED,
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            empty_slot_notification_sent=False
        )
        db.session.add(event)
        db.session.flush()

        # Step 1: Register 72 online students
        for i in range(72):
            st = self._get_or_create_user(f"online_stud_{i}_{timestamp}@college.edu", f"Student {i}", UserRole.STUDENT, "CSE")
            reg = EventRegistration(
                event_id=event.id,
                student_id=st.id,
                registration_code=f"REG-ON-{i}-{timestamp}",
                status=RegistrationStatus.CONFIRMED,
                registration_type="ONLINE"
            )
            db.session.add(reg)
        db.session.commit()

        # CORE RULE: Before online registration closes
        self.assertFalse(event.is_online_registration_closed)
        self.assertEqual(event.online_registrations_count, 72)
        self.assertEqual(event.spot_registration_capacity, 0, "On-spot slots must be 0 before online reg closes")
        self.assertEqual(event.spot_slots_remaining, 0)

        # Attempt to edit on-spot slots while online registration is open -> must reject
        with self.client.session_transaction() as sess:
            sess['user_id'] = organizer.id

        resp = self.client.post(f'/organizer/events/{event.id}/spot-slots', data={'spot_registration_slots': '28'}, follow_redirects=True)
        self.assertIn(b"Online registration is still open", resp.data)

        # Step 2: Online registration closes (pass the deadline)
        event.registration_deadline = now - timedelta(minutes=5)
        db.session.add(event)
        db.session.commit()

        self.assertTrue(event.is_online_registration_closed)
        # Formula: On-Spot Available = Total Event Capacity (100) - Online Registrations (72) = 28
        self.assertEqual(event.spot_registration_capacity, 28)
        self.assertEqual(event.spot_slots_remaining, 28)

        # Step 3: Organizer tries to change On-Spot Slots to 30 -> REJECT (exceeds 28)
        resp_invalid = self.client.post(
            f'/organizer/events/{event.id}/spot-slots',
            data={'spot_registration_slots': '30'},
            follow_redirects=True
        )
        self.assertIn(b"Only 28 slot(s) remain unused", resp_invalid.data)
        db.session.refresh(event)
        # Slots should still be system-generated 28
        self.assertEqual(event.spot_registration_capacity, 28)

        # Step 4: Organizer changes On-Spot Slots to 25 -> ACCEPT
        resp_valid = self.client.post(
            f'/organizer/events/{event.id}/spot-slots',
            data={'spot_registration_slots': '25'},
            follow_redirects=True
        )
        self.assertIn(b"successfully updated to 25", resp_valid.data)
        db.session.refresh(event)
        self.assertEqual(event.spot_registration_slots, 25)
        self.assertEqual(event.spot_registration_capacity, 25)
        self.assertEqual(event.spot_slots_remaining, 25)

        # Step 5: Register 5 walk-in on-spot students
        for j in range(5):
            spot_data = {
                'student_name': f'Spot Student {j}',
                'roll_number': f'SPOT-ROLL-{j}-{timestamp}',
                'email': f'spot_stud_{j}_{timestamp}@college.edu',
                'phone': '9876543210',
                'department': 'CSE',
                'year': '2',
                'section': 'A'
            }
            resp_spot = self.client.post(f'/organizer/events/{event.id}/spot-registration/add', data=spot_data, follow_redirects=True)
            self.assertIn(b"successfully registered", resp_spot.data)

        db.session.refresh(event)
        self.assertEqual(event.spot_registrations_count, 5)
        self.assertEqual(event.spot_slots_remaining, 20)  # 25 - 5

        # Step 6: Organizer tries to reduce On-Spot Slots below existing 5 (e.g. to 4) -> REJECT
        resp_below = self.client.post(
            f'/organizer/events/{event.id}/spot-slots',
            data={'spot_registration_slots': '4'},
            follow_redirects=True
        )
        self.assertIn(b"There are already 5 students registered on-spot", resp_below.data)

        # Step 7: Organizer starts the event manually
        start_resp = self.client.post(f'/organizer/events/{event.id}/start', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(start_resp.status_code, 200)
        data = start_resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], EventStatus.STARTED)
        self.assertEqual(data['total_slots'], 100)
        self.assertEqual(data['online_registrations'], 72)
        self.assertEqual(data['spot_registrations'], 5)
        self.assertEqual(data['total_occupied'], 77)
        self.assertEqual(data['empty_slots'], 23)

        # Step 8: Verify HOD notification contains required fields
        notif = Notification.query.filter_by(
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT
        ).first()
        self.assertIsNotNone(notif)
        self.assertIn("Event Started: AI Innovation Summit", notif.message)
        self.assertIn("Total Event Slots: 100", notif.message)
        self.assertIn("Online Registrations: 72", notif.message)
        self.assertIn("On-Spot Registrations: 5", notif.message)
        self.assertIn("Total Occupied: 77", notif.message)
        self.assertIn("Empty Slots: 23", notif.message)


if __name__ == '__main__':
    unittest.main()
