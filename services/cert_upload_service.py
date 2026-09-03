import os
import zipfile
import uuid
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import current_app
from models import db, Event, User, StudentProfile, EventRegistration, Certificate, CertificateStatus
from services.ocr_service import extract_text_from_file, extract_roll_number

ALLOWED_CERT_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}


def _get_event_cert_dir(event_id):
    """Returns the dedicated filesystem directory for an event's certificates."""
    base_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'certificates' / f"event_{event_id}"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def _is_safe_zip_path(target_dir, file_path):
    """Prevents ZIP slip / path traversal vulnerabilities."""
    resolved_target = Path(target_dir).resolve()
    resolved_file = (resolved_target / file_path).resolve()
    return resolved_target in resolved_file.parents or resolved_target == resolved_file.parent


def process_single_certificate_file(event, file_path, original_filename, registered_students_map, custom_pattern=None, uploader_user=None):
    """
    Processes one certificate file (PDF or Image):
    - Reads and extracts text using PDF parser or OCR.
    - Identifies the roll number.
    - Matches student from registered students map.
    - Determines status (MATCHED, UNMATCHED, DUPLICATE, INVALID).
    - Saves Certificate record in DB.
    """
    ext = Path(original_filename).suffix.lower().lstrip('.')
    file_type = 'pdf' if ext == 'pdf' else 'image'
    
    # 1. Extract text from the certificate file
    extracted_text = extract_text_from_file(file_path)
    
    if extracted_text and extracted_text.startswith('[') and 'Error:' in extracted_text:
        is_invalid = True
    else:
        is_invalid = False

    # 2. Extract roll number
    candidate_roll_numbers = list(registered_students_map.keys())
    extracted_roll = extract_roll_number(
        text=extracted_text,
        custom_pattern=custom_pattern,
        candidate_roll_numbers=candidate_roll_numbers,
        filename=original_filename
    )

    # 3. Match against registered students
    student = None
    registration = None
    status = CertificateStatus.UNMATCHED

    if is_invalid:
        status = CertificateStatus.INVALID
    elif extracted_roll:
        roll_key = extracted_roll.upper()
        if roll_key in registered_students_map:
            student, registration = registered_students_map[roll_key]
            
            # Check for existing certificate for this student in this event
            existing_cert = Certificate.query.filter_by(
                event_id=event.id,
                student_id=student.id
            ).filter(Certificate.status.in_([CertificateStatus.MATCHED, CertificateStatus.MANUALLY_ASSIGNED])).first()

            if existing_cert:
                status = CertificateStatus.DUPLICATE
            else:
                status = CertificateStatus.MATCHED
        else:
            status = CertificateStatus.UNMATCHED
    else:
        status = CertificateStatus.UNMATCHED

    # 4. Generate unique relative path for storage
    relative_path = f"uploads/certificates/event_{event.id}/{Path(file_path).name}"
    cert_code = Certificate.generate_certificate_code(event.id, student.id if student else None)

    cert = Certificate(
        event_id=event.id,
        student_id=student.id if student else None,
        registration_id=registration.id if registration else None,
        certificate_code=cert_code,
        roll_number=extracted_roll,
        file_path=relative_path,
        original_filename=original_filename,
        file_type=file_type,
        extracted_text=extracted_text[:4000] if extracted_text else "",
        status=status,
        assigned_by_id=uploader_user.id if uploader_user else None
    )
    db.session.add(cert)
    return cert


def process_certificate_uploads(event_id, files_list=None, zip_file=None, custom_pattern=None, uploader_user=None):
    """
    Handles multi-file and/or bulk ZIP upload of certificates:
    - Extracts ZIP safely if provided.
    - Saves all certificate files to disk.
    - Runs text extraction, OCR, roll-number identification, and student matching.
    - Returns comprehensive summary statistics and created certificate objects.
    """
    event = Event.query.get_or_404(event_id)
    dest_dir = _get_event_cert_dir(event.id)

    # Build registered students lookup map: {ROLL_NUMBER_UPPER: (User, EventRegistration)}
    registrations = EventRegistration.query.filter_by(event_id=event.id).all()
    registered_students_map = {}
    for r in registrations:
        if r.student and r.student.student_profile and r.student.student_profile.roll_number:
            roll = r.student.student_profile.roll_number.strip().upper()
            registered_students_map[roll] = (r.student, r)

    created_certs = []
    files_to_process = []  # List of tuples: (local_file_path, original_filename)

    # 1. Process individual file uploads
    if files_list:
        for file_storage in files_list:
            if not file_storage or not file_storage.filename:
                continue
            orig_name = secure_filename(file_storage.filename)
            ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else ''
            
            if ext == 'zip':
                # Process as ZIP
                zip_file = file_storage
            elif ext in ALLOWED_CERT_EXTENSIONS:
                unique_name = f"{uuid.uuid4().hex[:8]}_{orig_name}"
                target_path = dest_dir / unique_name
                file_storage.save(str(target_path))
                files_to_process.append((target_path, orig_name))

    # 2. Process ZIP archive if uploaded
    if zip_file and zip_file.filename:
        try:
            with zipfile.ZipFile(zip_file.stream if hasattr(zip_file, 'stream') else zip_file) as zf:
                for member in zf.infolist():
                    # Skip directories and macOS hidden resource files
                    if member.is_dir() or member.filename.startswith('__MACOSX') or Path(member.filename).name.startswith('.'):
                        continue

                    ext = member.filename.rsplit('.', 1)[-1].lower() if '.' in member.filename else ''
                    if ext not in ALLOWED_CERT_EXTENSIONS:
                        continue

                    safe_basename = secure_filename(Path(member.filename).name)
                    if not safe_basename:
                        continue

                    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_basename}"
                    target_path = dest_dir / unique_name

                    # Extract file content safely
                    with zf.open(member) as source, open(target_path, 'wb') as target:
                        target.write(source.read())

                    files_to_process.append((target_path, safe_basename))
        except Exception as e:
            pass

    # 3. Execute OCR / Matching on all collected certificate files
    for local_path, original_name in files_to_process:
        try:
            cert_obj = process_single_certificate_file(
                event=event,
                file_path=local_path,
                original_filename=original_name,
                registered_students_map=registered_students_map,
                custom_pattern=custom_pattern,
                uploader_user=uploader_user
            )
            created_certs.append(cert_obj)
        except Exception as e:
            # Handle individual processing failure
            rel_path = f"uploads/certificates/event_{event.id}/{local_path.name}"
            fail_cert = Certificate(
                event_id=event.id,
                certificate_code=Certificate.generate_certificate_code(event.id),
                file_path=rel_path,
                original_filename=original_name,
                file_type='pdf' if original_name.lower().endswith('.pdf') else 'image',
                extracted_text=f"Error: {str(e)}",
                status=CertificateStatus.INVALID,
                assigned_by_id=uploader_user.id if uploader_user else None
            )
            db.session.add(fail_cert)
            created_certs.append(fail_cert)

    db.session.commit()

    # Calculate statistics
    matched_count = len([c for c in created_certs if c.status == CertificateStatus.MATCHED])
    unmatched_count = len([c for c in created_certs if c.status == CertificateStatus.UNMATCHED])
    duplicate_count = len([c for c in created_certs if c.status == CertificateStatus.DUPLICATE])
    invalid_count = len([c for c in created_certs if c.status == CertificateStatus.INVALID])

    return {
        'total_uploaded': len(created_certs),
        'matched': matched_count,
        'unmatched': unmatched_count,
        'duplicate': duplicate_count,
        'invalid': invalid_count,
        'certificates': created_certs
    }


def manual_assign_certificate(cert_id, student_id, roll_number=None, assigned_by_user=None):
    """
    Manually associates an unmatched/duplicate certificate with a registered student.
    Immediately makes the certificate available to the student.
    """
    cert = Certificate.query.get_or_404(cert_id)
    student = User.query.get_or_404(student_id)

    # Find the student's registration for this event
    registration = EventRegistration.query.filter_by(
        event_id=cert.event_id,
        student_id=student.id
    ).first()

    profile = student.student_profile
    effective_roll = roll_number or (profile.roll_number if profile else "N/A")

    cert.student_id = student.id
    cert.registration_id = registration.id if registration else None
    cert.roll_number = effective_roll
    cert.status = CertificateStatus.MANUALLY_ASSIGNED
    cert.assigned_by_id = assigned_by_user.id if assigned_by_user else None

    db.session.commit()
    return cert


def _delete_cert_file(relative_path):
    """Safely removes a certificate file from static uploads directory."""
    if not relative_path:
        return
    try:
        base_dir = Path(__file__).resolve().parent.parent / 'static'
        target = base_dir / relative_path
        if target.exists() and target.is_file():
            target.unlink(missing_ok=True)
    except Exception:
        pass


def resolve_duplicate_certificate(cert_id, action, current_user=None):
    """
    Handles duplicate certificate resolution:
    - 'replace': Deletes previous certificate for this student in this event, marks this one as MATCHED.
    - 'keep_both': Sets this certificate status to MATCHED alongside existing.
    - 'discard': Deletes this certificate record and removes file from disk.
    """
    cert = Certificate.query.get_or_404(cert_id)
    
    if action == 'discard':
        _delete_cert_file(cert.file_path)
        db.session.delete(cert)
        db.session.commit()
        return "discarded"

    elif action == 'keep_both':
        cert.status = CertificateStatus.MATCHED
        db.session.commit()
        return "kept_both"

    elif action == 'replace':
        # Find other certificates for same event & student
        old_certs = Certificate.query.filter(
            Certificate.event_id == cert.event_id,
            Certificate.student_id == cert.student_id,
            Certificate.id != cert.id
        ).all()
        for old in old_certs:
            _delete_cert_file(old.file_path)
            db.session.delete(old)

        cert.status = CertificateStatus.MATCHED
        db.session.commit()
        return "replaced"

    return "unknown"


def delete_single_certificate(cert_id):
    """Deletes a certificate and removes its physical file from disk."""
    cert = Certificate.query.get_or_404(cert_id)
    _delete_cert_file(cert.file_path)
    db.session.delete(cert)
    db.session.commit()

