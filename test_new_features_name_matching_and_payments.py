import os
import io
import unittest
from unittest import mock
from datetime import datetime
from PIL import Image, ImageDraw

from app import create_app
from config import Config
from models import (
    db, User, Event, EventRegistration, RegistrationStatus,
    Certificate, CertificateStatus, Payment, PaymentStatus
)
from services.name_matching_service import (
    normalize_name, calculate_name_similarity, extract_candidate_names_from_text,
    match_certificate_to_student
)
from services.payment_verification_service import normalize_transaction_id, check_duplicate_event_transaction


def create_sample_receipt_image(text="UPI Ref 123456789012"):
    img = Image.new('RGB', (600, 300), color='#ffffff')
    draw = ImageDraw.Draw(img)
    draw.text((30, 50), text, fill='#000000')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.getvalue()


class NewFeaturesValidationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_name_normalization_and_similarity(self):
        """Test name normalization rules and similarity calculation."""
        self.assertEqual(normalize_name("  Dr. Jane   A.  Doe  "), "jane a doe")
        self.assertEqual(normalize_name("R. K. Narayan"), "r k narayan")
        self.assertEqual(normalize_name("ARAVIND  KUMAR-SHARMA"), "aravind kumar sharma")

        # Exact match
        sim = calculate_name_similarity("Aarav Sharma", "aarav sharma")
        self.assertEqual(sim, 1.0)

        # Reordered tokens (e.g. Sharma Aarav vs Aarav Sharma)
        sim_reordered = calculate_name_similarity("Sharma Aarav", "Aarav Sharma")
        self.assertGreaterEqual(sim_reordered, 0.90)

        # Minor typo
        sim_typo = calculate_name_similarity("Aarav Sharrma", "Aarav Sharma")
        self.assertGreaterEqual(sim_typo, 0.85)

        # Different person
        sim_diff = calculate_name_similarity("John Smith", "Aarav Sharma")
        self.assertLess(sim_diff, 0.40)

    def test_name_matching_rules(self):
        """Test exact, fuzzy, ambiguous, and unmatched rules for certificates."""
        registered_students = [
            {'student_id': 101, 'name': 'Aditi Rao', 'roll_number': '23CS001', 'registration_id': 501},
            {'student_id': 102, 'name': 'Aditya Rao', 'roll_number': '23CS002', 'registration_id': 502},
            {'student_id': 103, 'name': 'Rohan Sharma', 'roll_number': '23CS003', 'registration_id': 503},
        ]

        # 1. Exact match
        text_exact = "This is to certify that Rohan Sharma has won first prize in Coding Contest."
        res_exact = match_certificate_to_student(text_exact, registered_students)
        self.assertEqual(res_exact['status'], CertificateStatus.MATCHED_AUTOMATICALLY)
        self.assertEqual(res_exact['matched_student_id'], 103)
        self.assertEqual(res_exact['confidence_score'], 1.0)

        # 2. Ambiguous match (Aditi Rao vs Aditya Rao close scores)
        text_ambig = "Certificate presented to Aditi Ra for participation."
        res_ambig = match_certificate_to_student(text_ambig, registered_students)
        self.assertIn(res_ambig['status'], [CertificateStatus.PENDING_MANUAL_REVIEW, CertificateStatus.MATCHED_AUTOMATICALLY])

        # 3. Completely unmatched
        text_unmatched = "Certificate awarded to Jessica Brown for Excellence."
        res_unmatched = match_certificate_to_student(text_unmatched, registered_students)
        self.assertEqual(res_unmatched['status'], CertificateStatus.UNMATCHED)
        self.assertIsNone(res_unmatched['matched_student_id'])

    def test_payment_txn_normalization_and_duplicate(self):
        """Test transaction ID normalization and duplicate checking."""
        self.assertEqual(normalize_transaction_id("  UPI-1234-5678-ABCD  "), "UPI12345678ABCD")
        self.assertEqual(normalize_transaction_id("txn_98765"), "TXN98765")
        self.assertEqual(normalize_transaction_id("  "), "")

        with self.app.app_context():
            # Check duplicate event transaction function exists and runs
            is_dup, reason = check_duplicate_event_transaction(event_id=999999, transaction_id="NON_EXISTENT_TXN")
            self.assertFalse(is_dup)
            self.assertIsNone(reason)

    def test_certificate_vault_visibility_and_assignment(self):
        """Test that only MATCHED_AUTOMATICALLY or ASSIGNED_MANUALLY appear in student vault."""
        with self.app.app_context():
            # Test Certificate properties
            cert_auto = Certificate(
                event_id=1,
                student_id=10,
                certificate_code="CERT-AUTO-1",
                original_filename="test.pdf",
                file_path="uploads/certificates/test.pdf",
                extracted_name="Aarav Sharma",
                confidence_score=0.98,
                status=CertificateStatus.MATCHED_AUTOMATICALLY
            )
            self.assertTrue(cert_auto.is_assigned)
            self.assertEqual(cert_auto.status_label, "Matched Automatically")

            cert_pending = Certificate(
                event_id=1,
                certificate_code="CERT-PENDING-1",
                original_filename="pending.pdf",
                file_path="uploads/certificates/pending.pdf",
                extracted_name="Aarav S",
                confidence_score=0.72,
                status=CertificateStatus.PENDING_MANUAL_REVIEW
            )
            self.assertFalse(cert_pending.is_assigned)
            self.assertEqual(cert_pending.status_label, "Pending Manual Review")

            cert_manual = Certificate(
                event_id=1,
                student_id=10,
                certificate_code="CERT-MANUAL-1",
                original_filename="manual.pdf",
                file_path="uploads/certificates/manual.pdf",
                extracted_name="Aarav Sharma",
                confidence_score=0.60,
                status=CertificateStatus.ASSIGNED_MANUALLY
            )
            self.assertTrue(cert_manual.is_assigned)
            self.assertEqual(cert_manual.status_label, "Assigned Manually")

            cert_unmatched = Certificate(
                event_id=1,
                certificate_code="CERT-UNMATCHED-1",
                original_filename="unmatched.pdf",
                file_path="uploads/certificates/unmatched.pdf",
                status=CertificateStatus.UNMATCHED
            )
            self.assertFalse(cert_unmatched.is_assigned)
            self.assertEqual(cert_unmatched.status_label, "Unmatched")

    def test_payment_status_properties_and_badges(self):
        """Test payment status model properties and registration badge rendering."""
        with self.app.app_context():
            p_verified = Payment(
                amount=200.0,
                transaction_id="TXN123456",
                extracted_transaction_id="TXN123456",
                status=PaymentStatus.TRANSACTION_ID_VERIFIED
            )
            self.assertTrue(p_verified.is_transaction_id_verified)
            self.assertFalse(p_verified.is_verification_failed)
            self.assertEqual(p_verified.status_label, "Transaction ID Verified")

            p_failed = Payment(
                amount=200.0,
                transaction_id="TXN123456",
                extracted_transaction_id="TXN999999",
                status=PaymentStatus.PAYMENT_VERIFICATION_FAILED
            )
            self.assertFalse(p_failed.is_transaction_id_verified)
            self.assertTrue(p_failed.is_verification_failed)
            self.assertEqual(p_failed.status_label, "Payment Verification Failed")


if __name__ == '__main__':
    unittest.main()
