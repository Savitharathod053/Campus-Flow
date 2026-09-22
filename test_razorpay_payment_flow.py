import unittest
import hmac
import hashlib
import json
from datetime import datetime, timedelta
from app import create_app
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile,
    Event, EventRegistration, RegistrationStatus, Payment, PaymentStatus
)
from services.razorpay_service import (
    create_razorpay_order,
    verify_payment_signature,
    verify_webhook_signature,
    process_successful_payment,
    process_failed_payment
)
from unittest.mock import patch, MagicMock

class RazorpayPaymentFlowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['RAZORPAY_KEY_ID'] = 'rzp_test_campusflow_test_key'
        cls.app.config['RAZORPAY_KEY_SECRET'] = 'secret_test_key_campusflow_123'
        cls.app.config['RAZORPAY_WEBHOOK_SECRET'] = 'webhook_test_secret_campusflow_456'
        cls.client = cls.app.test_client()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

        # Create unique test organizer
        rand_id = int(datetime.utcnow().timestamp() * 1000) % 1000000
        self.organizer = User(
            name=f"Razor Organizer {rand_id}",
            email=f"rzp_org_{rand_id}@college.edu",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        self.organizer.set_password("SecurePass123!")
        db.session.add(self.organizer)
        db.session.flush()

        # Create unique test student
        self.student = User(
            name=f"Razor Student {rand_id}",
            email=f"rzp_stu_{rand_id}@college.edu",
            role=UserRole.STUDENT,
            is_active=True
        )
        self.student.set_password("SecurePass123!")
        db.session.add(self.student)
        db.session.flush()

        profile = StudentProfile(
            user_id=self.student.id,
            roll_number=f"ROLL-RZP-{rand_id}",
            department="CSE",
            year=3,
            section="A"
        )
        db.session.add(profile)

        # Create paid active event
        self.event = Event(
            title=f"National Hackathon {rand_id}",
            slug=f"national-hackathon-{rand_id}",
            description="A grand tech event.",
            event_type="Hackathon",
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            organizer_id=self.organizer.id,
            start_time=datetime.utcnow() + timedelta(days=5),
            end_time=datetime.utcnow() + timedelta(days=6),
            registration_deadline=datetime.utcnow() + timedelta(days=4),
            venue="Tech Lab 1",
            is_published=True,
            hod_approved=True,
            dean_approved=True,
            status="REGISTRATION_OPEN",
            is_free=False,
            registration_fee=250.0
        )
        db.session.add(self.event)
        db.session.flush()

        # Create student registration
        self.reg_code = f"CF-E{self.event.id}-S{self.student.id}-TEST"
        self.registration = EventRegistration(
            event_id=self.event.id,
            student_id=self.student.id,
            registration_code=self.reg_code,
            status=RegistrationStatus.PENDING_PAYMENT
        )
        db.session.add(self.registration)
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        # Clean up created records
        Payment.query.filter_by(event_id=self.event.id).delete()
        EventRegistration.query.filter_by(event_id=self.event.id).delete()
        Event.query.filter_by(id=self.event.id).delete()
        StudentProfile.query.filter_by(user_id=self.student.id).delete()
        User.query.filter(User.id.in_([self.student.id, self.organizer.id])).delete()
        db.session.commit()
        self.ctx.pop()

    @patch('services.razorpay_service.get_razorpay_client')
    def test_01_create_razorpay_order(self, mock_get_client):
        """Test order creation: amount converted to paise, Payment in PENDING status."""
        mock_client = MagicMock()
        mock_client.order.create.return_value = {
            'id': 'order_test_123456789',
            'amount': 25000,
            'currency': 'INR',
            'receipt': self.reg_code,
            'status': 'created'
        }
        mock_get_client.return_value = mock_client

        order_data = create_razorpay_order(self.registration)
        self.assertEqual(order_data['order_id'], 'order_test_123456789')
        self.assertEqual(order_data['amount'], 25000)
        self.assertEqual(order_data['currency'], 'INR')
        self.assertEqual(order_data['receipt'], self.reg_code)

        # Verify Payment record in database
        payment = Payment.query.filter_by(registration_id=self.registration.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.razorpay_order_id, 'order_test_123456789')
        self.assertEqual(payment.amount, 250.0)
        self.assertEqual(payment.payment_method, 'RAZORPAY')
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertTrue(payment.is_razorpay)

    def test_02_payment_signature_verification(self):
        """Test HMAC-SHA256 signature verification."""
        order_id = "order_test_signature_999"
        payment_id = "pay_test_signature_888"
        secret = self.app.config['RAZORPAY_KEY_SECRET']

        # Generate valid signature
        msg = f"{order_id}|{payment_id}".encode('utf-8')
        valid_signature = hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()

        # Test valid signature passes
        self.assertTrue(verify_payment_signature(order_id, payment_id, valid_signature))

        # Test invalid signature fails
        self.assertFalse(verify_payment_signature(order_id, payment_id, "invalid_tampered_signature_12345"))

        # Test mismatched order ID fails
        self.assertFalse(verify_payment_signature("order_wrong_id", payment_id, valid_signature))

    def test_03_webhook_signature_verification(self):
        """Test webhook HMAC-SHA256 signature validation."""
        raw_payload = b'{"event":"payment.captured","id":"evt_test_001"}'
        webhook_secret = self.app.config['RAZORPAY_WEBHOOK_SECRET']

        valid_sig = hmac.new(webhook_secret.encode('utf-8'), raw_payload, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_signature(raw_payload, valid_sig))
        self.assertFalse(verify_webhook_signature(raw_payload, "tampered_webhook_signature"))

    def test_04_process_successful_payment_and_idempotency(self):
        """Test payment verification, ticket issuance, and idempotent duplicate handling."""
        # Create a pending payment
        payment = Payment(
            registration_id=self.registration.id,
            event_id=self.event.id,
            student_id=self.student.id,
            organizer_id=self.organizer.id,
            amount=250.0,
            currency='INR',
            razorpay_order_id='order_reconcile_test_1',
            payment_method='RAZORPAY',
            status=PaymentStatus.PENDING
        )
        db.session.add(payment)
        db.session.commit()

        # 1. First execution: should confirm registration and generate ticket QR
        pmt, ok, msg = process_successful_payment(
            razorpay_order_id='order_reconcile_test_1',
            razorpay_payment_id='pay_reconcile_test_1',
            razorpay_signature='sig_test_1'
        )
        self.assertTrue(ok)
        self.assertEqual(pmt.status, PaymentStatus.VERIFIED)
        self.assertEqual(pmt.razorpay_payment_id, 'pay_reconcile_test_1')
        self.assertEqual(pmt.transaction_id, 'pay_reconcile_test_1')
        self.assertIsNotNone(pmt.verified_at)

        reg = EventRegistration.query.get(self.registration.id)
        self.assertEqual(reg.status, RegistrationStatus.CONFIRMED)
        self.assertIsNotNone(reg.qr_code_image)
        self.assertTrue(reg.is_confirmed)

        # 2. Idempotent duplicate call (e.g. repeated webhook or retry):
        # Should return cleanly without duplicating or modifying existing confirmation
        pmt2, ok2, msg2 = process_successful_payment(
            razorpay_order_id='order_reconcile_test_1',
            razorpay_payment_id='pay_reconcile_test_1'
        )
        self.assertTrue(ok2)
        self.assertIn("idempotent", msg2.lower())
        self.assertEqual(pmt2.id, pmt.id)

    def test_05_process_failed_payment(self):
        """Test recording failed payment for audit."""
        payment = Payment(
            registration_id=self.registration.id,
            event_id=self.event.id,
            student_id=self.student.id,
            organizer_id=self.organizer.id,
            amount=250.0,
            currency='INR',
            razorpay_order_id='order_failed_test_1',
            payment_method='RAZORPAY',
            status=PaymentStatus.PENDING
        )
        db.session.add(payment)
        db.session.commit()

        failed_pmt = process_failed_payment(
            razorpay_order_id='order_failed_test_1',
            razorpay_payment_id='pay_failed_1',
            failure_reason='Bank server timeout'
        )
        self.assertEqual(failed_pmt.status, PaymentStatus.PAYMENT_VERIFICATION_FAILED)
        self.assertEqual(failed_pmt.failure_reason, 'Bank server timeout')

    @patch('services.razorpay_service.get_razorpay_client')
    def test_06_http_routes_checkout_and_verification(self, mock_get_client):
        """Test client-side order creation and verification endpoints."""
        mock_client = MagicMock()
        mock_client.order.create.return_value = {
            'id': 'order_api_test_555',
            'amount': 25000,
            'currency': 'INR',
            'receipt': self.reg_code
        }
        mock_get_client.return_value = mock_client

        # Login as student
        with self.client.session_transaction() as sess:
            sess['_user_id'] = self.student.id
            sess['user_id'] = self.student.id
            sess['user_role'] = UserRole.STUDENT

        # 1. Call create-order endpoint
        res = self.client.post(f'/payment/razorpay/create-order/{self.registration.id}')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertTrue(data['success'])
        self.assertEqual(data['order']['order_id'], 'order_api_test_555')

        # 2. Compute valid signature for verification endpoint
        secret = self.app.config['RAZORPAY_KEY_SECRET']
        payment_id = 'pay_api_test_666'
        msg = f"order_api_test_555|{payment_id}".encode('utf-8')
        sig = hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()

        # 3. Call verify endpoint
        verify_res = self.client.post(
            '/payment/razorpay/verify',
            json={
                'registration_id': self.registration.id,
                'razorpay_order_id': 'order_api_test_555',
                'razorpay_payment_id': payment_id,
                'razorpay_signature': sig
            }
        )
        self.assertEqual(verify_res.status_code, 200)
        v_data = json.loads(verify_res.data)
        self.assertTrue(v_data['success'])
        self.assertIn('ticket', v_data['redirect_url'])

        # Verify registration in DB is now confirmed with ticket QR
        reg = EventRegistration.query.get(self.registration.id)
        self.assertTrue(reg.is_confirmed)
        self.assertIsNotNone(reg.qr_code_image)

    def test_07_http_webhook_captured_event(self):
        """Test machine-to-machine Razorpay webhook endpoint (/api/payments/webhook/razorpay)."""
        # Create a pending payment
        payment = Payment(
            registration_id=self.registration.id,
            event_id=self.event.id,
            student_id=self.student.id,
            organizer_id=self.organizer.id,
            amount=250.0,
            currency='INR',
            razorpay_order_id='order_webhook_live_777',
            payment_method='RAZORPAY',
            status=PaymentStatus.PENDING
        )
        db.session.add(payment)
        db.session.commit()

        webhook_payload = {
            "entity": "event",
            "account_id": "acc_campusflow",
            "event": "payment.captured",
            "id": "evt_hook_123456",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_webhook_live_888",
                        "order_id": "order_webhook_live_777",
                        "amount": 25000,
                        "currency": "INR",
                        "status": "captured"
                    }
                }
            }
        }
        raw_body = json.dumps(webhook_payload).encode('utf-8')
        secret = self.app.config['RAZORPAY_WEBHOOK_SECRET']
        signature = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()

        # Post to /api/payments/webhook/razorpay
        res = self.client.post(
            '/api/payments/webhook/razorpay',
            data=raw_body,
            headers={
                'Content-Type': 'application/json',
                'X-Razorpay-Signature': signature
            }
        )
        self.assertEqual(res.status_code, 200)
        resp_json = json.loads(res.data)
        self.assertEqual(resp_json.get('status'), 'ok')

        # Check DB updated
        pmt = Payment.query.get(payment.id)
        self.assertEqual(pmt.status, PaymentStatus.VERIFIED)
        self.assertEqual(pmt.razorpay_payment_id, "pay_webhook_live_888")
        self.assertEqual(pmt.webhook_event_id, "evt_hook_123456")

        reg = EventRegistration.query.get(self.registration.id)
        self.assertTrue(reg.is_confirmed)
        self.assertIsNotNone(reg.qr_code_image)

        # Retrying the same webhook (idempotency) should return 200 without error
        res_retry = self.client.post(
            '/api/payments/webhook/razorpay',
            data=raw_body,
            headers={
                'Content-Type': 'application/json',
                'X-Razorpay-Signature': signature
            }
        )
        self.assertEqual(res_retry.status_code, 200)

    def test_08_tampered_webhook_rejected(self):
        """Test that webhooks with fraudulent or missing signatures are rejected."""
        raw_body = b'{"event":"payment.captured"}'
        res = self.client.post(
            '/api/payments/webhook/razorpay',
            data=raw_body,
            headers={
                'Content-Type': 'application/json',
                'X-Razorpay-Signature': 'fake_signature_attempt'
            }
        )
        self.assertEqual(res.status_code, 400)


if __name__ == '__main__':
    unittest.main()
