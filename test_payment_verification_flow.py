import os
import io
import unittest
from unittest import mock
import uuid
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, PngImagePlugin
from app import create_app
from config import Config
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    Payment, PaymentStatus, FraudRisk
)
from services.payment_verification_service import analyze_image_fraud

class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    SERVER_NAME = 'localhost'
    PAYMENT_PROOF_FOLDER = 'static/uploads/test_payment_proofs'
    ORGANIZER_QR_FOLDER = 'static/uploads/test_organizer_qrs'

def create_sample_receipt_image(text="Amount Rs 500.00 Ref 123456789012", metadata_software=None):
    """Generates an in-memory PNG image simulating a payment receipt screenshot."""
    img = Image.new('RGB', (400, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 390, 80], fill=(240, 240, 245))
    draw.text((20, 30), "PAYMENT SUCCESSFUL", fill=(0, 128, 0))
    draw.text((20, 120), text, fill=(0, 0, 0))
    draw.line([(20, 160), (380, 160)], fill=(200, 200, 200), width=2)
    draw.text((20, 180), "State Bank UPI", fill=(50, 50, 50))
    
    buf = io.BytesIO()
    if metadata_software:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("Software", metadata_software)
        img.save(buf, format='PNG', pnginfo=pnginfo)
    else:
        img.save(buf, format='PNG')
    buf.seek(0)
    return buf

class TestPaymentVerificationFlow(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        self.client = self.app.test_client()

        os.makedirs(TestConfig.PAYMENT_PROOF_FOLDER, exist_ok=True)
        os.makedirs(TestConfig.ORGANIZER_QR_FOLDER, exist_ok=True)

        uid = uuid.uuid4().hex[:6]

        # 1. Organizer 1 (Event Owner)
        self.org_user = User(
            name=f"Club Lead {uid}",
            email=f"org_{uid}@college.edu",
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

        # 2. Organizer 2 (Different Organizer)
        self.other_org_user = User(
            name=f"Other Lead {uid}",
            email=f"other_org_{uid}@college.edu",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        self.other_org_user.set_password("pass123")
        db.session.add(self.other_org_user)
        db.session.commit()

        self.other_org_profile = OrganizerProfile(
            user_id=self.other_org_user.id,
            organization_name="Dance Club",
            department="ECE",
            status="APPROVED",
            is_verified=True
        )
        db.session.add(self.other_org_profile)

        # 3. Student 1 (Applicant)
        self.student_user = User(
            name=f"Alice Student {uid}",
            email=f"alice_{uid}@college.edu",
            role=UserRole.STUDENT,
            is_active=True
        )
        self.student_user.set_password("pass123")
        db.session.add(self.student_user)
        db.session.commit()

        self.student_profile = StudentProfile(
            user_id=self.student_user.id,
            roll_number=f"CSE{uid}1",
            department="CSE",
            year=3,
            section="A"
        )
        db.session.add(self.student_profile)

        # 4. Student 2 (Other Student)
        self.other_student_user = User(
            name=f"Bob Student {uid}",
            email=f"bob_{uid}@college.edu",
            role=UserRole.STUDENT,
            is_active=True
        )
        self.other_student_user.set_password("pass123")
        db.session.add(self.other_student_user)
        db.session.commit()

        self.other_student_profile = StudentProfile(
            user_id=self.other_student_user.id,
            roll_number=f"CSE{uid}2",
            department="CSE",
            year=2,
            section="B"
        )
        db.session.add(self.other_student_profile)

        # 5. Paid Event created by Organizer 1
        now = datetime.utcnow()
        self.paid_event = Event(
            title="Cloud & AI Workshop",
            slug=f"cloud-ai-workshop-{uid}",
            description="Hands on workshop",
            organizer_id=self.org_user.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            venue="Seminar Hall A",
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=3),
            registration_deadline=now + timedelta(days=1),
            registration_fee=500.0,
            is_free=False,
            status=EventStatus.APPROVED,
            upi_id="techclub@okaxis",
            upi_number="9876543210",
            payment_instructions="Please pay Rs. 500 to our UPI ID or Phone"
        )
        db.session.add(self.paid_event)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    # ------------------------------------------------------------------------
    # TEST CASE 1: Valid proof + amount -> PENDING/LOW RISK -> Organizer verifies -> VERIFIED -> Ticket generated
    # ------------------------------------------------------------------------
    def test_case_1_valid_proof_organizer_verification(self):
        # 1. Student registers for the event
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE1-100"
        )
        db.session.add(reg)
        db.session.commit()

        # 2. Student uploads payment proof
        img_bytes = create_sample_receipt_image(text="Amount Rs 500.00 Ref 123456789012")
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        data = {
            'registration_id': reg.id,
            'transaction_id': '123456789012',
            'payment_method': 'UPI_DIRECT',
            'payment_screenshot': (img_bytes, 'receipt.png')
        }
        res = self.client.post(f'/payment/submit-proof/{reg.id}', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # 3. Check Payment record: Must be PENDING (no automatic ticket issuance)
        payment = Payment.query.filter_by(registration_id=reg.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertEqual(payment.transaction_id, '123456789012')
        self.assertEqual(payment.expected_amount, 500.0)

        # Registration must NOT yet be confirmed and no QR ticket yet
        db.session.refresh(reg)
        self.assertEqual(reg.status, RegistrationStatus.PENDING_PAYMENT)
        self.assertIsNone(reg.qr_code_image)
        self.assertFalse(reg.is_paid)

        # 4. Organizer logs in and verifies the payment
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.org_user.id

        verify_res = self.client.post(f'/organizer/payments/{payment.id}/verify', data={'notes': 'Looks good'}, follow_redirects=True)
        self.assertEqual(verify_res.status_code, 200)

        # 5. Check Payment is now VERIFIED and ticket QR is generated
        db.session.refresh(payment)
        db.session.refresh(reg)
        self.assertEqual(payment.status, PaymentStatus.VERIFIED)
        self.assertEqual(reg.status, RegistrationStatus.CONFIRMED)
        self.assertIsNotNone(reg.qr_code_image)
        self.assertTrue(reg.is_paid)

    # ------------------------------------------------------------------------
    # TEST CASE 2: Event fee ₹500, screenshot ₹300 -> REJECTED, no ticket
    # ------------------------------------------------------------------------
    def test_case_2_wrong_amount_rejected(self):
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE2"
        )
        db.session.add(reg)
        db.session.commit()

        img_bytes = create_sample_receipt_image(text="Amount Rs 300.00 Ref 123456789012")
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        # Mock OCR output detecting Rs. 300
        with mock.patch('services.payment_verification_service.extract_text_from_screenshot', return_value="Paid to Tech Club Amount: Rs 300.00 UTR: 123456789012"):
            data = {
                'registration_id': reg.id,
                'transaction_id': '123456789012',
                'payment_method': 'UPI_DIRECT',
                'payment_screenshot': (img_bytes, 'receipt_300.png')
            }
            res = self.client.post(f'/payment/submit-proof/{reg.id}', data=data, content_type='multipart/form-data', follow_redirects=True)
            self.assertEqual(res.status_code, 200)

        payment = Payment.query.filter_by(registration_id=reg.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, PaymentStatus.REJECTED)
        self.assertEqual(payment.detected_amount, 300.0)
        self.assertIn("amount does not match", payment.verification_reason.lower())

        # Ticket must NOT be issued
        db.session.refresh(reg)
        self.assertEqual(reg.status, RegistrationStatus.PENDING_PAYMENT)
        self.assertIsNone(reg.qr_code_image)
        self.assertFalse(reg.is_paid)

    # ------------------------------------------------------------------------
    # TEST CASE 3: Student-entered transaction ID doesn't match screenshot -> REJECTED
    # ------------------------------------------------------------------------
    def test_case_3_txn_id_mismatch_rejected(self):
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE3"
        )
        db.session.add(reg)
        db.session.commit()

        img_bytes = create_sample_receipt_image(text="Amount Rs 500.00 Ref 999988887777")
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        # Mock OCR extracting 999988887777, but student entered 111122223333
        with mock.patch('services.payment_verification_service.extract_text_from_screenshot', return_value="Paid to Tech Club Amount: Rs 500.00 UTR: 999988887777"):
            data = {
                'registration_id': reg.id,
                'transaction_id': '111122223333',
                'payment_method': 'UPI_DIRECT',
                'payment_screenshot': (img_bytes, 'receipt_wrong_txn.png')
            }
            res = self.client.post(f'/payment/submit-proof/{reg.id}', data=data, content_type='multipart/form-data', follow_redirects=True)
            self.assertEqual(res.status_code, 200)

        payment = Payment.query.filter_by(registration_id=reg.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, PaymentStatus.PAYMENT_VERIFICATION_FAILED)
        self.assertIn("transaction id does not match", payment.verification_reason.lower())

        # No ticket generated
        db.session.refresh(reg)
        self.assertEqual(reg.status, RegistrationStatus.PENDING_PAYMENT)
        self.assertIsNone(reg.qr_code_image)

    # ------------------------------------------------------------------------
    # TEST CASE 4: Duplicate transaction ID -> REJECTED
    # ------------------------------------------------------------------------
    def test_case_4_duplicate_txn_id_rejected(self):
        # First student already registered and has verified payment with TXN_EXISTING_123
        reg_existing = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.CONFIRMED,
            registration_code="REG-EXISTING-1"
        )
        db.session.add(reg_existing)
        db.session.commit()

        existing_pay = Payment(
            registration_id=reg_existing.id,
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            organizer_id=self.org_user.id,
            amount=500.0,
            expected_amount=500.0,
            detected_amount=500.0,
            transaction_id='TXN_EXISTING_123',
            screenshot_hash='hash_existing_1',
            status=PaymentStatus.VERIFIED
        )
        db.session.add(existing_pay)
        db.session.commit()

        # Second student registers and tries to submit the same transaction ID
        reg2 = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.other_student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE4-DUP"
        )
        db.session.add(reg2)
        db.session.commit()

        img_bytes = create_sample_receipt_image(text="Amount Rs 500.00 Ref TXN_EXISTING_123")
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.other_student_user.id

        data = {
            'registration_id': reg2.id,
            'transaction_id': 'TXN_EXISTING_123',
            'payment_method': 'UPI_DIRECT',
            'payment_screenshot': (img_bytes, 'dup_receipt.png')
        }
        res = self.client.post(f'/payment/submit-proof/{reg2.id}', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Payment for second student must be REJECTED as duplicate
        pay2 = Payment.query.filter_by(registration_id=reg2.id).first()
        self.assertIsNotNone(pay2)
        self.assertEqual(pay2.status, PaymentStatus.REJECTED)
        self.assertIn("already been used", pay2.verification_reason.lower())

        # No ticket for student 2
        db.session.refresh(reg2)
        self.assertEqual(reg2.status, RegistrationStatus.PENDING_PAYMENT)
        self.assertIsNone(reg2.qr_code_image)

    # ------------------------------------------------------------------------
    # TEST CASE 5: Manipulated/suspicious screenshot -> HIGH RISK / MANUAL REVIEW
    # ------------------------------------------------------------------------
    def test_case_5_manipulated_screenshot_manual_review(self):
        # 1. Test analyze_image_fraud identifies Photoshop in metadata
        buf = create_sample_receipt_image(metadata_software="Adobe Photoshop 2024")
        temp_path = os.path.join(TestConfig.PAYMENT_PROOF_FOLDER, "temp_photoshop_test.png")
        with open(temp_path, "wb") as f:
            f.write(buf.getvalue())

        fraud_risk, fraud_indicators = analyze_image_fraud(temp_path)
        if os.path.exists(temp_path):
            os.remove(temp_path)

        self.assertEqual(fraud_risk, FraudRisk.HIGH)
        self.assertTrue(any("Photoshop" in r for r in fraud_indicators))

        # 2. Test submission routing to MANUAL_REVIEW
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE5"
        )
        db.session.add(reg)
        db.session.commit()

        img_bytes = create_sample_receipt_image(text="Amount Rs 500.00 Ref 123456789012", metadata_software="Adobe Photoshop 2024")
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        data = {
            'registration_id': reg.id,
            'transaction_id': '123456789012',
            'payment_method': 'UPI_DIRECT',
            'payment_screenshot': (img_bytes, 'photoshop_receipt.png')
        }
        res = self.client.post(f'/payment/submit-proof/{reg.id}', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        payment = Payment.query.filter_by(registration_id=reg.id).first()
        self.assertIsNotNone(payment)
        self.assertEqual(payment.fraud_risk, FraudRisk.HIGH)
        self.assertEqual(payment.status, PaymentStatus.MANUAL_REVIEW)

        # No automatic ticket generated
        db.session.refresh(reg)
        self.assertEqual(reg.status, RegistrationStatus.PENDING_PAYMENT)
        self.assertIsNone(reg.qr_code_image)

    # ------------------------------------------------------------------------
    # TEST CASE 6: Unverified payment -> Ticket access denied
    # ------------------------------------------------------------------------
    def test_case_6_unverified_payment_ticket_denied(self):
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE6-UNVERIFIED"
        )
        db.session.add(reg)
        db.session.commit()

        # Payment is submitted and PENDING
        payment = Payment(
            registration_id=reg.id,
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            organizer_id=self.org_user.id,
            amount=500.0,
            status=PaymentStatus.PENDING,
            transaction_id="TXN_UNVERIFIED_99"
        )
        db.session.add(payment)
        db.session.commit()

        # Student attempts to view ticket
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        res = self.client.get(f'/student/ticket/{reg.registration_code}', follow_redirects=True)
        self.assertIn(b"Payment is required before your ticket", res.data)

    # ------------------------------------------------------------------------
    # TEST CASE 7: Student attempting to alter payment status via API -> Denied
    # ------------------------------------------------------------------------
    def test_case_7_student_cannot_verify_payment(self):
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE7"
        )
        db.session.add(reg)
        db.session.commit()

        payment = Payment(
            registration_id=reg.id,
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            organizer_id=self.org_user.id,
            amount=500.0,
            status=PaymentStatus.PENDING,
            transaction_id="TXN_HACK_77"
        )
        db.session.add(payment)
        db.session.commit()

        # Student logs in and tries to POST to organizer verify endpoint
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.student_user.id

        res = self.client.post(f'/organizer/payments/{payment.id}/verify')
        # Role required is ORGANIZER; student is redirected with permission denied flash
        self.assertIn(res.status_code, [302, 403])

        # Verify payment status remained PENDING
        db.session.refresh(payment)
        self.assertEqual(payment.status, PaymentStatus.PENDING)

    # ------------------------------------------------------------------------
    # TEST CASE 8: Student viewing another student's payment screenshot -> 403
    # ------------------------------------------------------------------------
    def test_case_8_student_cannot_view_other_proof(self):
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE8"
        )
        db.session.add(reg)
        db.session.commit()

        payment = Payment(
            registration_id=reg.id,
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            organizer_id=self.org_user.id,
            amount=500.0,
            status=PaymentStatus.PENDING,
            transaction_id="TXN_SECRET_88",
            payment_screenshot="dummy_screenshot.png"
        )
        db.session.add(payment)
        db.session.commit()

        # Other student logs in and tries to view Student 1's proof
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.other_student_user.id

        res = self.client.get(f'/payment/proof/{payment.id}')
        self.assertEqual(res.status_code, 403)

    # ------------------------------------------------------------------------
    # TEST CASE 9: Organizer verifying an event belonging to another organizer -> 403
    # ------------------------------------------------------------------------
    def test_case_9_unauthorized_organizer_cannot_verify(self):
        reg = EventRegistration(
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            status=RegistrationStatus.PENDING_PAYMENT,
            registration_code="REG-CASE9"
        )
        db.session.add(reg)
        db.session.commit()

        payment = Payment(
            registration_id=reg.id,
            event_id=self.paid_event.id,
            student_id=self.student_user.id,
            organizer_id=self.org_user.id,
            amount=500.0,
            status=PaymentStatus.PENDING,
            transaction_id="TXN_OTHERORG_99"
        )
        db.session.add(payment)
        db.session.commit()

        # Other Organizer (not the event owner) logs in and attempts to verify
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.other_org_user.id

        res = self.client.post(f'/organizer/payments/{payment.id}/verify')
        self.assertEqual(res.status_code, 403)

        # Payment must remain PENDING
        db.session.refresh(payment)
        self.assertEqual(payment.status, PaymentStatus.PENDING)

if __name__ == '__main__':
    unittest.main()
