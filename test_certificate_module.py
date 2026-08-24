import os
import io
import unittest
import zipfile
import uuid
from pathlib import Path
from PIL import Image, ImageDraw
from app import create_app
from config import Config
from models import (
    db, User, StudentProfile, Event, EventRegistration, RegistrationStatus,
    Certificate, CertificateStatus, EventStatus
)
from services.ocr_service import extract_text_from_file, extract_roll_number
from services.cert_upload_service import (
    process_certificate_uploads, manual_assign_certificate,
    resolve_duplicate_certificate, delete_single_certificate
)

def create_sample_text_pdf(text_content):
    """Creates a valid, lightweight PDF with native selectable text."""
    escaped_text = text_content.replace('(', r'\(').replace(')', r'\)')
    stream_content = f"BT /F1 18 Tf 50 700 Td ({escaped_text}) Tj ET"
    stream_len = len(stream_content)
    pdf_string = (
        "%PDF-1.4\n"
        "1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n"
        "2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n"
        "3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources <</Font <</F1 5 0 R>>>>>> endobj\n"
        f"4 0 obj <</Length {stream_len}>> stream\n"
        f"{stream_content}\n"
        "endstream endobj\n"
        "5 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n"
        "xref\n"
        "0 6\n"
        "0000000000 65535 f \n"
        "0000000009 00000 n \n"
        "0000000058 00000 n \n"
        "0000000115 00000 n \n"
        "0000000244 00000 n \n"
        "0000000300 00000 n \n"
        "trailer <</Size 6 /Root 1 0 R>>\n"
        "startxref\n"
        "370\n"
        "%%EOF"
    )
    return pdf_string.encode('latin-1')


def create_sample_image(text_content):
    """Creates a sample certificate image using Pillow."""
    img = Image.new('RGB', (800, 400), color='#ffffff')
    draw = ImageDraw.Draw(img)
    draw.text((50, 100), text_content, fill='#000000')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf.getvalue()


class CertificateModuleTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_01_text_extraction_and_roll_number_matching(self):
        """Test PDF text extraction and configurable roll number parsing."""
        sample_pdf_bytes = create_sample_text_pdf("FastFest Certificate - Presented to Rahul. Roll No: 23DS001 for Workshop.")
        temp_pdf = Path("test_sample_cert.pdf")
        temp_pdf.write_bytes(sample_pdf_bytes)

        try:
            extracted_text = extract_text_from_file(temp_pdf)
            self.assertIn("23DS001", extracted_text)

            roll = extract_roll_number(extracted_text, candidate_roll_numbers=["23DS001", "23DS002"])
            self.assertEqual(roll, "23DS001")
        finally:
            if temp_pdf.exists():
                temp_pdf.unlink()

    def test_02_bulk_multi_file_and_zip_upload(self):
        """Test uploading individual certificates and a ZIP archive with auto-matching."""
        with self.app.app_context():
            event = Event.query.first()
            self.assertIsNotNone(event)

            # Clear existing certificates for event in test
            Certificate.query.filter_by(event_id=event.id).delete()
            db.session.commit()

            # Ensure we have registered students
            regs = EventRegistration.query.filter_by(event_id=event.id).all()
            if not regs:
                student = User.query.filter_by(role='STUDENT').first()
                reg = EventRegistration(
                    event_id=event.id,
                    student_id=student.id,
                    registration_code=EventRegistration.generate_registration_code(event.id, student.id),
                    status=RegistrationStatus.CONFIRMED
                )
                db.session.add(reg)
                db.session.commit()
                regs = [reg]

            reg1 = regs[0]
            student1 = reg1.student
            if not student1.student_profile:
                student1.student_profile = StudentProfile(user_id=student1.id, roll_number='23DS001', department='CSE', year=3, section='A')
                db.session.commit()

            roll1 = student1.student_profile.roll_number.strip().upper()

            # Create test ZIP containing a matched certificate and an unmatched certificate
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, 'w') as zf:
                # File 1: contains student roll number (Matched)
                zf.writestr("cert_matched.pdf", create_sample_text_pdf(f"Certificate of Excellence - Roll No: {roll1}"))
                # File 2: contains unknown roll number (Unmatched)
                zf.writestr("cert_unmatched.pdf", create_sample_text_pdf("Certificate of Excellence - Roll No: UNKNOWN999"))

            zip_buf.seek(0)
            zip_file_obj = io.BytesIO(zip_buf.getvalue())
            zip_file_obj.filename = "certificates_batch.zip"

            org = event.organizer
            report = process_certificate_uploads(
                event_id=event.id,
                zip_file=zip_file_obj,
                uploader_user=org
            )

            self.assertEqual(report['total_uploaded'], 2)
            self.assertEqual(report['matched'], 1)
            self.assertEqual(report['unmatched'], 1)

    def test_03_manual_assignment_and_duplicate_resolution(self):
        """Test manual assignment of an unmatched certificate and resolving duplicates."""
        with self.app.app_context():
            event = Event.query.first()
            student = User.query.filter_by(role='STUDENT').first()
            org = event.organizer

            # 1. Create an unmatched certificate record
            unmatched_cert = Certificate(
                event_id=event.id,
                certificate_code=Certificate.generate_certificate_code(event.id),
                original_filename="manual_fix_test.pdf",
                file_path="uploads/certificates/manual_fix_test.pdf",
                file_type="pdf",
                extracted_text="Raw illegible text",
                status=CertificateStatus.UNMATCHED
            )
            db.session.add(unmatched_cert)
            db.session.commit()
            cert_id = unmatched_cert.id

            # 2. Manually assign to student
            assigned = manual_assign_certificate(
                cert_id=cert_id,
                student_id=student.id,
                assigned_by_user=org
            )
            self.assertEqual(assigned.status, CertificateStatus.MANUALLY_ASSIGNED)
            self.assertEqual(assigned.student_id, student.id)

            # 3. Create a duplicate certificate for this student
            dup_cert = Certificate(
                event_id=event.id,
                student_id=student.id,
                certificate_code=Certificate.generate_certificate_code(event.id, student.id),
                original_filename="duplicate_copy.pdf",
                file_path="uploads/certificates/duplicate_copy.pdf",
                file_type="pdf",
                status=CertificateStatus.DUPLICATE
            )
            db.session.add(dup_cert)
            db.session.commit()

            # Resolve duplicate by 'keep_both'
            res = resolve_duplicate_certificate(dup_cert.id, action="keep_both", current_user=org)
            self.assertEqual(res, "kept_both")
            self.assertEqual(dup_cert.status, CertificateStatus.MATCHED)

    def test_04_student_access_control_and_security(self):
        """Verify students can ONLY view/download their own certificates and cannot tamper with IDs."""
        with self.app.app_context():
            students = User.query.filter_by(role='STUDENT').all()
            if len(students) < 2:
                self.skipTest("Requires at least two student accounts for authorization security test.")

            student_a = students[0]
            student_b = students[1]
            event = Event.query.first()

            # Create certificate assigned to Student A
            cert_a = Certificate(
                event_id=event.id,
                student_id=student_a.id,
                certificate_code=Certificate.generate_certificate_code(event.id, student_a.id),
                original_filename="student_a_cert.pdf",
                file_path="uploads/certificates/student_a_cert.pdf",
                file_type="pdf",
                status=CertificateStatus.MATCHED
            )
            db.session.add(cert_a)
            db.session.commit()
            cert_a_id = cert_a.id

            # Create dummy file on disk for download/preview
            upload_dir = Path(self.app.config['UPLOAD_FOLDER']) / 'certificates'
            upload_dir.mkdir(parents=True, exist_ok=True)
            (upload_dir / "student_a_cert.pdf").write_bytes(b"%PDF-1.4 sample")

            # Login as Student B (unauthorized for cert_a)
            with self.client.session_transaction() as sess:
                sess['user_id'] = student_b.id

            # Student B attempts to download Student A's certificate -> MUST BE 403 FORBIDDEN
            res_download = self.client.get(f"/student/certificates/{cert_a_id}/download")
            self.assertEqual(res_download.status_code, 403)

            # Student B attempts to preview Student A's certificate -> MUST BE 403 FORBIDDEN
            res_preview = self.client.get(f"/student/certificates/{cert_a_id}/preview")
            self.assertEqual(res_preview.status_code, 403)

            # Login as Student A (authorized)
            with self.client.session_transaction() as sess:
                sess['user_id'] = student_a.id

            # Student A downloads own certificate -> MUST BE 200 OK
            res_auth = self.client.get(f"/student/certificates/{cert_a_id}/download")
            self.assertEqual(res_auth.status_code, 200)
            res_auth.close()

            # Clean up dummy file and cert
            try:
                db.session.delete(cert_a)
                db.session.commit()
            except Exception:
                pass

            if (upload_dir / "student_a_cert.pdf").exists():
                try:
                    (upload_dir / "student_a_cert.pdf").unlink()
                except Exception:
                    pass

if __name__ == '__main__':
    unittest.main()
