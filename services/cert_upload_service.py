import os
import zipfile
import uuid
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import current_app
from models import db, Event, User, StudentProfile, EventRegistration, Certificate, CertificateStatus
from services.ocr_service import extract_text_from_file, extract_roll_number
from services.name_matching_service import match_certificate_to_student

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
    - Matches student primarily by Student Name from OCR text using name_matching_service.
    - Falls back to roll number if name matching is inconclusive.
    - Sets status (MATCHED_AUTOMATICALLY, PENDING_MANUAL_REVIEW, UNMATCHED, DUPLICATE, INVALID).
    - Saves Certificate record in DB with extracted_name and confidence_score.
    """
    ext = Path(original_filename).suffix.lower().lstrip('.')
    file_type = 'pdf' if ext == 'pdf' else 'image'
    
    # 1. Normalize registered students list
    if isinstance(registered_students_map, dict):
        registered_students_list = []
        for roll, (s_user, s_reg) in registered_students_map.items():
            registered_students_list.append({
                'student_id': s_user.id,
                'name': s_user.name,
                'roll_number': roll,
                'registration_id': s_reg.id if s_reg else None,
                'user': s_user,
                'registration': s_reg
            })
    else:
        registered_students_list = registered_students_map or []

    # 2. Extract text from the certificate file
    extracted_text = extract_text_from_file(file_path)
    
    if extracted_text and extracted_text.startswith('[') and 'Error:' in extracted_text:
        is_invalid = True
    else:
        is_invalid = False

    # 3. Match against registered students by Student Name (primary)
    student = None
    registration = None
    extracted_roll = None
    extracted_name = None
    confidence_score = 0.0

    if is_invalid:
        status = CertificateStatus.INVALID
    else:
        match_result = match_certificate_to_student(extracted_text, registered_students_list)
        status = match_result.get('status', CertificateStatus.UNMATCHED)
        matched_student_id = match_result.get('matched_student_id')
        matched_reg_id = match_result.get('matched_registration_id')
        extracted_name = match_result.get('extracted_name')
        confidence_score = match_result.get('confidence_score', 0.0)

        # Fallback roll number extraction for record-keeping
        candidate_rolls = [s.get('roll_number') for s in registered_students_list if s.get('roll_number')]
        extracted_roll = extract_roll_number(
            text=extracted_text,
            custom_pattern=custom_pattern,
            candidate_roll_numbers=candidate_rolls,
            filename=original_filename
        )

        if status == CertificateStatus.MATCHED_AUTOMATICALLY and matched_student_id:
            # Find matched student & registration objects
            for s_info in registered_students_list:
                if s_info['student_id'] == matched_student_id:
                    student = s_info.get('user') or User.query.get(matched_student_id)
                    registration = s_info.get('registration') or (EventRegistration.query.get(matched_reg_id) if matched_reg_id else None)
                    if not extracted_roll and s_info.get('roll_number'):
                        extracted_roll = s_info.get('roll_number')
                    break

            # Check for existing certificate for this student in this event
            existing_cert = Certificate.query.filter_by(
                event_id=event.id,
                student_id=matched_student_id
            ).filter(Certificate.status.in_([
                CertificateStatus.MATCHED_AUTOMATICALLY,
                CertificateStatus.ASSIGNED_MANUALLY,
                'MATCHED',
                'MANUALLY_ASSIGNED'
            ])).first()

            if existing_cert:
                status = CertificateStatus.DUPLICATE
        elif status == CertificateStatus.PENDING_MANUAL_REVIEW:
            # For pending manual review, do NOT automatically attach to student vault
            student = None
            registration = None

    # 4. Generate unique relative path for storage
    relative_path = f"uploads/certificates/event_{event.id}/{Path(file_path).name}"
    cert_code = Certificate.generate_certificate_code(event.id, student.id if student else None)

    cert = Certificate(
        event_id=event.id,
        student_id=student.id if (student and status == CertificateStatus.MATCHED_AUTOMATICALLY) else None,
        registration_id=registration.id if (registration and status == CertificateStatus.MATCHED_AUTOMATICALLY) else None,
        certificate_code=cert_code,
        roll_number=extracted_roll,
        extracted_name=extracted_name,
        confidence_score=confidence_score,
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

    # Build registered students list and lookup map:
    registrations = EventRegistration.query.filter_by(event_id=event.id).all()
    registered_students_list = []
    registered_students_map = {}
    for r in registrations:
        if r.student:
            roll = r.student.student_profile.roll_number.strip().upper() if r.student.student_profile and r.student.student_profile.roll_number else None
            student_entry = {
                'student_id': r.student.id,
                'name': r.student.name,
                'roll_number': roll,
                'registration_id': r.id,
                'user': r.student,
                'registration': r
            }
            registered_students_list.append(student_entry)
            if roll:
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
                registered_students_map=registered_students_list,
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

    # Dispatch certificate ready notifications for successfully matched students
    try:
        from services.email_service import send_certificate_ready_email
        from services.notification_service import create_notification
        from models.notification import NotificationType
        for c in created_certs:
            if c.status in (CertificateStatus.MATCHED_AUTOMATICALLY, 'MATCHED') and c.student:
                create_notification(
                    user_id=c.student.id,
                    title=f"Certificate Ready: {event.title}",
                    message=f"Your certificate for '{event.title}' has been issued and is ready for download in your vault.",
                    notification_type=NotificationType.SYSTEM,
                    link="/student/certificates"
                )
                send_certificate_ready_email(c, c.student, event)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch certificate ready notifications/emails: {exc}")

    # Calculate statistics
    matched_count = len([c for c in created_certs if c.status in (CertificateStatus.MATCHED_AUTOMATICALLY, 'MATCHED')])
    pending_count = len([c for c in created_certs if c.status == CertificateStatus.PENDING_MANUAL_REVIEW])
    unmatched_count = len([c for c in created_certs if c.status == CertificateStatus.UNMATCHED])
    duplicate_count = len([c for c in created_certs if c.status == CertificateStatus.DUPLICATE])
    invalid_count = len([c for c in created_certs if c.status == CertificateStatus.INVALID])

    return {
        'total_uploaded': len(created_certs),
        'matched': matched_count,
        'pending': pending_count,
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
    cert.status = CertificateStatus.ASSIGNED_MANUALLY
    cert.assigned_by_id = assigned_by_user.id if assigned_by_user else None

    db.session.commit()

    # Dispatch certificate ready notification
    try:
        from services.email_service import send_certificate_ready_email
        from services.notification_service import create_notification
        from models.notification import NotificationType
        event = Event.query.get(cert.event_id)
        if event and student:
            create_notification(
                user_id=student.id,
                title=f"Certificate Ready: {event.title}",
                message=f"Your certificate for '{event.title}' has been issued and is ready for download in your vault.",
                notification_type=NotificationType.SYSTEM,
                link="/student/certificates"
            )
            send_certificate_ready_email(cert, student, event)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch certificate ready notification/email: {exc}")

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

