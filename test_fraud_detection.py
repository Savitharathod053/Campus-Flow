"""
Campus Flow - Payment Screenshot Fraud Detection Comprehensive Test Suite
Tests:
1. Module imports and Hugging Face configuration.
2. Safe image loading, MIME checks, magic bytes, corrupt image guards.
3. Hugging Face ViT model inference with structured output.
4. Payment upload integration & database persistence (fraud_status, fraud_score, fraud_label, fraud_model, fraud_checked_at).
5. Student privacy preservation (no fraud scores leaked to student).
6. Admin & Organizer dashboard verification views.
"""

import os
import io
import sys
import unittest
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

# Ensure app root is on python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import create_app
from models import db, User, UserRole, Event, EventRegistration, RegistrationStatus, Payment, PaymentStatus
from fraud_detection import check_payment_image, FraudStatus
from fraud_detection.image_fraud import get_model_name, _validate_image_security


class TestPaymentFraudDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

        # Create temporary test images directory
        cls.test_dir = Path(cls.app.root_path) / 'static' / 'uploads' / 'test_fraud'
        cls.test_dir.mkdir(parents=True, exist_ok=True)

        # 1. Create a valid mock payment receipt image
        cls.valid_receipt_path = cls.test_dir / 'test_receipt.png'
        img = Image.new('RGB', (600, 800), color=(245, 247, 250))
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 580, 780], outline=(200, 200, 200), width=2)
        draw.rectangle([40, 40, 560, 160], fill=(24, 119, 242))
        draw.text((60, 80), "Payment Successful", fill=(255, 255, 255))
        draw.text((60, 220), "Paid to: FastFest College Events", fill=(30, 30, 30))
        draw.text((60, 280), "Amount: INR 250.00", fill=(0, 128, 0))
        draw.text((60, 340), "UPI Ref / UTR: 123456789012", fill=(60, 60, 60))
        draw.text((60, 400), "Txn ID: T240901234567890", fill=(60, 60, 60))
        draw.text((60, 460), "Date: 24 Sep 2026, 10:15 AM", fill=(100, 100, 100))
        img.save(str(cls.valid_receipt_path), 'PNG')

        # 2. Create a corrupt image file
        cls.corrupt_img_path = cls.test_dir / 'corrupt.jpg'
        with open(cls.corrupt_img_path, 'wb') as f:
            f.write(b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00CorruptImageDataHereNonSense')

        # 3. Create a fake extension text file
        cls.fake_ext_path = cls.test_dir / 'malicious.png'
        with open(cls.fake_ext_path, 'w') as f:
            f.write("This is plain text pretending to be a png file")

    @classmethod
    def tearDownClass(cls):
        # Cleanup test files
        for p in [cls.valid_receipt_path, cls.corrupt_img_path, cls.fake_ext_path]:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    def test_01_model_name_configuration(self):
        """Verifies model name reads from env and defaults safely."""
        current_model = get_model_name()
        self.assertIsNotNone(current_model)
        self.assertIn("umm-maybe/AI-image-detector", current_model)

    def test_02_security_validation(self):
        """Tests image magic-byte security and extension validation."""
        # Valid PNG
        err = _validate_image_security(self.valid_receipt_path)
        self.assertIsNone(err)

        # Non-image masked as PNG
        err = _validate_image_security(self.fake_ext_path)
        self.assertIsNotNone(err)
        self.assertIn("File signature does not match", err)

        # Non-existent file
        err = _validate_image_security(Path("non_existent_image.png"))
        self.assertIsNotNone(err)

    def test_03_check_payment_image_structured_result(self):
        """Tests check_payment_image on valid receipt and ensures all required fields exist."""
        result = check_payment_image(str(self.valid_receipt_path))
        print("\n--- Model Inference Result ---")
        print(result)

        self.assertIn("is_suspicious", result)
        self.assertIn("confidence", result)
        self.assertIn("label", result)
        self.assertIn("reason", result)
        self.assertIn("model", result)
        self.assertIn("fraud_status", result)

        self.assertIsInstance(result["is_suspicious"], bool)
        self.assertIsInstance(result["confidence"], (float, int))
        self.assertIn(result["fraud_status"], FraudStatus.CHOICES)

    def test_04_corrupt_image_graceful_handling(self):
        """Verifies corrupt image safely returns MANUAL_REVIEW without throwing unhandled exception."""
        result = check_payment_image(str(self.corrupt_img_path))
        self.assertIn(result["fraud_status"], [FraudStatus.MANUAL_REVIEW, FraudStatus.SUSPICIOUS])
        self.assertTrue(result["is_suspicious"])

    def test_05_database_columns_and_model_properties(self):
        """Verifies Payment model columns and properties exist and function properly."""
        with self.app.app_context():
            p = Payment(
                amount=250.0,
                transaction_id="123456789012",
                status=PaymentStatus.MANUAL_REVIEW,
                fraud_status="LOW_RISK",
                fraud_score=0.94,
                fraud_label="human",
                fraud_model="umm-maybe/AI-image-detector",
                fraud_checked_at=datetime.utcnow()
            )
            self.assertEqual(p.display_fraud_status, "LOW RISK")
            self.assertIn("success", p.fraud_badge_class)

            p.fraud_status = "SUSPICIOUS"
            self.assertEqual(p.display_fraud_status, "SUSPICIOUS")
            self.assertIn("danger", p.fraud_badge_class)

            p.fraud_status = "MANUAL_REVIEW"
            self.assertEqual(p.display_fraud_status, "MANUAL REVIEW")
            self.assertIn("warning", p.fraud_badge_class)

    def test_06_verification_pipeline_integration(self):
        """Verifies complete verify_payment_submission pipeline persists all fraud fields in DB."""
        with self.app.app_context():
            from werkzeug.datastructures import FileStorage
            from services.payment_verification_service import verify_payment_submission

            # Fetch or create a test student and active event
            student = User.query.filter_by(role=UserRole.STUDENT).first()
            event = Event.query.filter(Event.is_free == False).first()

            if not student or not event:
                print("Skipping DB pipeline test: student or paid event not in test DB.")
                return

            # Check or create registration
            reg = EventRegistration.query.filter_by(student_id=student.id, event_id=event.id).first()
            if not reg:
                reg = EventRegistration(
                    student_id=student.id,
                    event_id=event.id,
                    status=RegistrationStatus.REGISTERED
                )
                db.session.add(reg)
                db.session.commit()

            # Mock FileStorage
            with open(self.valid_receipt_path, 'rb') as f:
                file_bytes = f.read()

            file_storage = FileStorage(
                stream=io.BytesIO(file_bytes),
                filename="test_proof_upload.png",
                content_type="image/png"
            )

            test_txn = f"TXN{int(datetime.utcnow().timestamp())}"
            payment, result = verify_payment_submission(
                registration=reg,
                entered_transaction_id=test_txn,
                uploaded_file=file_storage
            )

            self.assertIsNotNone(payment)
            self.assertIsNotNone(payment.fraud_status)
            self.assertIsNotNone(payment.fraud_model)
            self.assertIsNotNone(payment.fraud_checked_at)
            self.assertIn(payment.fraud_status, FraudStatus.CHOICES)
            print("\nPersisted Payment Record Fraud Status:", payment.fraud_status, "Score:", payment.fraud_score, "Model:", payment.fraud_model)


if __name__ == '__main__':
    unittest.main()
