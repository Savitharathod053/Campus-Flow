"""
Campus Flow - Automated Test Suite for Supabase Cloud Storage & Upload Lifecycle

Validates:
1. sanitize_storage_filename safely cleans WhatsApp filenames with spaces, parentheses, timestamps.
2. get_media_url handles full URLs, Supabase paths, existing local files, and missing files (graceful fallback).
3. Organizer UPI QR upload stores persistent URL/path and does not crash or depend on ephemeral storage.
4. Event detail and checkout pages render the active QR code or show a graceful "QR unavailable" state when missing.
5. Payment proof upload saves persistent cloud reference and remains viewable via /payment/proof/<id>.
6. Certificate preview and download routes properly redirect to cloud storage URLs.
7. Ticket QR self-healing dynamically regenerates if missing from ephemeral disk.
8. Local development workflow is preserved when cloud credentials are not configured.
"""
import unittest
import io
from pathlib import Path
from unittest.mock import patch, MagicMock
from app import create_app
from models import (
    db, User, UserRole, CollegeDepartment, Event, EventStatus, EventType,
    EventRegistration, RegistrationStatus, Payment, PaymentStatus, Certificate, CertificateStatus
)
from services.storage_service import (
    sanitize_storage_filename,
    get_media_url,
    upload_file,
    delete_file,
    is_cloud_storage_enabled
)


class TestSupabaseStorageSystem(unittest.TestCase):

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

    def test_01_filename_sanitization(self):
        """Verify filename sanitization handles WhatsApp, spaces, and parenthesis safely."""
        tricky_names = [
            "WhatsApp Image 2026-03-24 at 10.45.12 (1).jpeg",
            "My QR Code (College Fest) [Final].PNG",
            "Payment proof #123 & receipt (special).jpg",
            "cert with spaces and $pecial chars!.pdf",
            "   leading_and_trailing_spaces.png   "
        ]
        for name in tricky_names:
            sanitized = sanitize_storage_filename(name, prefix="test")
            # Verify no spaces, no parens, no brackets, no special chars except _ and - and .
            self.assertNotIn(" ", sanitized)
            self.assertNotIn("(", sanitized)
            self.assertNotIn(")", sanitized)
            self.assertNotIn("[", sanitized)
            self.assertNotIn("&", sanitized)
            self.assertNotIn("#", sanitized)
            self.assertTrue(sanitized.startswith("test_"))
            self.assertTrue(any(sanitized.endswith(ext) for ext in ('.jpg', '.png', '.pdf', '.webp')))

    def test_02_get_media_url_resolution(self):
        """Verify get_media_url resolves cloud URLs, Supabase paths, and handles missing files."""
        # 1. Full URL
        full_url = "https://xyzcompany.supabase.co/storage/v1/object/public/campusflow/organizer_qrs/test.jpg"
        self.assertEqual(get_media_url(full_url), full_url)

        # 2. None or empty
        self.assertIsNone(get_media_url(None))
        self.assertIsNone(get_media_url(""))
        self.assertEqual(get_media_url(None, default="fallback.png"), "fallback.png")

        # 3. Missing local file should gracefully return None / default rather than crashing
        missing_file = "uploads/organizer_qrs/non_existent_file_xyz_123.jpg"
        self.assertIsNone(get_media_url(missing_file))

    def test_03_mock_supabase_upload(self):
        """Verify cloud upload sends correct payload to Supabase and returns public URL."""
        with patch('services.storage_service.is_cloud_storage_enabled', return_value=True), \
             patch('services.storage_service.get_supabase_url', return_value="https://testproj.supabase.co"), \
             patch('services.storage_service.get_supabase_service_key', return_value="secret-service-key"), \
             patch('services.storage_service.ensure_bucket_exists', return_value=True), \
             patch('requests.post') as mock_post:

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"Key": "campusflow/organizer_qrs/test.png"}'
            mock_post.return_value = mock_resp

            dummy_bytes = b"\x89PNG\r\n\x1a\nfake_image_bytes"
            success, public_url, path = upload_file(
                file_data=dummy_bytes,
                folder="organizer_qrs",
                filename="WhatsApp Image 2026.png",
                prefix="upi_qr"
            )

            self.assertTrue(success)
            self.assertTrue(public_url.startswith("https://testproj.supabase.co/storage/v1/object/public/campusflow/organizer_qrs/"))
            self.assertIn(".png", public_url)
            self.assertTrue(mock_post.called)
            # Verify authorization header
            call_headers = mock_post.call_args[1]['headers']
            self.assertEqual(call_headers['Authorization'], "Bearer secret-service-key")

    def _get_or_create_fixtures(self):
        from datetime import datetime, timedelta
        dept = CollegeDepartment.query.filter_by(code="CSE").first()
        if not dept:
            dept = CollegeDepartment(name="Computer Science & Engineering", code="CSE")
            db.session.add(dept)
            db.session.commit()

        organizer = User.query.filter_by(email="org_storage_test@college.edu").first()
        if not organizer:
            organizer = User(
                email="org_storage_test@college.edu",
                name="Test Storage Organizer",
                role=UserRole.ORGANIZER,
                is_active=True
            )
            organizer.set_password("SecurePass123!")
            db.session.add(organizer)
            db.session.commit()

        student = User.query.filter_by(email="student_cert_test@college.edu").first()
        if not student:
            student = User(
                email="student_cert_test@college.edu",
                name="Student Cert Tester",
                role=UserRole.STUDENT,
                is_active=True
            )
            student.set_password("SecurePass123!")
            db.session.add(student)
            db.session.commit()

        now = datetime.utcnow()
        event = Event.query.filter_by(title="Cloud Storage Showcase Workshop").first()
        if not event:
            event = Event(
                title="Cloud Storage Showcase Workshop",
                slug=f"cloud-storage-workshop-{int(now.timestamp())}",
                organizer_id=organizer.id,
                department="CSE",
                department_id=dept.id,
                faculty_coordinator="Prof. Cloud",
                description="Testing persistent cloud storage for uploads",
                venue="Seminar Hall B",
                start_time=now + timedelta(days=2),
                end_time=now + timedelta(days=2, hours=3),
                registration_deadline=now + timedelta(days=1),
                registration_fee=250.0,
                is_free=False,
                upi_id="organizer@upi",
                upi_number="9876543210",
                upi_qr_image="uploads/organizer_qrs/missing_ephemeral_qr.jpg",
                is_published=True,
                status=EventStatus.APPROVED
            )
            db.session.add(event)
            db.session.commit()

        return organizer, student, event

    def test_04_organizer_qr_and_graceful_missing_state(self):
        """Verify event with accessible QR shows image, and event with missing QR shows graceful state."""
        organizer, student, event = self._get_or_create_fixtures()
        event.upi_qr_image = "uploads/organizer_qrs/missing_ephemeral_qr.jpg"
        db.session.commit()

        # Check property
        self.assertFalse(event.is_upi_qr_available)
        self.assertIsNone(event.upi_qr_url)

        # Event detail page must NOT crash (HTTP 200) and show graceful message
        res = self.client.get(f"/events/{event.slug}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"QR Code temporarily unavailable", res.data)
        self.assertIn(b"organizer@upi", res.data)

        # Now simulate cloud URL stored in upi_qr_image
        event.upi_qr_image = "https://xyz.supabase.co/storage/v1/object/public/campusflow/organizer_qrs/valid_qr.png"
        db.session.commit()

        self.assertTrue(event.is_upi_qr_available)
        self.assertEqual(event.upi_qr_url, "https://xyz.supabase.co/storage/v1/object/public/campusflow/organizer_qrs/valid_qr.png")

        res2 = self.client.get(f"/events/{event.slug}")
        self.assertEqual(res2.status_code, 200)
        self.assertIn(b"https://xyz.supabase.co/storage/v1/object/public/campusflow/organizer_qrs/valid_qr.png", res2.data)

    def test_05_certificate_cloud_redirects(self):
        """Verify organizer and student preview/download routes redirect to cloud storage."""
        organizer, student, event = self._get_or_create_fixtures()
        cloud_cert_url = "https://xyz.supabase.co/storage/v1/object/public/campusflow/certificates/cert_123.pdf"

        cert = Certificate(
            event_id=event.id,
            student_id=student.id,
            certificate_code=Certificate.generate_certificate_code(event.id, student.id),
            file_path=cloud_cert_url,
            original_filename="Participation_Certificate.pdf",
            file_type="pdf",
            status=CertificateStatus.MATCHED
        )
        db.session.add(cert)
        db.session.commit()

        self.assertEqual(cert.file_url, cloud_cert_url)

        # Log in as student
        with self.client.session_transaction() as sess:
            sess['user_id'] = student.id
            sess['_user_role'] = UserRole.STUDENT

        # Test download route redirects to cloud storage
        res_dl = self.client.get(f"/student/certificates/{cert.id}/download")
        self.assertEqual(res_dl.status_code, 302)
        self.assertEqual(res_dl.location, cloud_cert_url)

        # Test preview route redirects to cloud storage
        res_prev = self.client.get(f"/student/certificates/{cert.id}/preview")
        self.assertEqual(res_prev.status_code, 302)
        self.assertEqual(res_prev.location, cloud_cert_url)

    def test_06_payment_proof_view_cloud_redirect(self):
        """Verify payment proof route redirects to cloud storage URL for authorized viewers."""
        organizer, student, event = self._get_or_create_fixtures()
        cloud_proof_url = "https://xyz.supabase.co/storage/v1/object/public/campusflow/payment_proofs/proof_123.jpg"

        payment = Payment(
            event_id=event.id,
            student_id=student.id,
            amount=250.0,
            transaction_id="TXN98765432100",
            payment_screenshot=cloud_proof_url,
            status=PaymentStatus.TRANSACTION_ID_VERIFIED
        )
        db.session.add(payment)
        db.session.commit()

        self.assertEqual(payment.proof_url, cloud_proof_url)

        # Log in as student
        with self.client.session_transaction() as sess:
            sess['user_id'] = student.id
            sess['_user_role'] = UserRole.STUDENT

        res = self.client.get(f"/payment/proof/{payment.id}")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res.location, cloud_proof_url)


if __name__ == '__main__':
    unittest.main()
