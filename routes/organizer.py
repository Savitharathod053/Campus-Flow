from datetime import datetime
import io
import os
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, jsonify, send_file, current_app, abort
)
from models import (
    db, Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    CustomRegistrationField, CustomFieldResponse, Payment, PaymentStatus,
    AttendanceRecord, VerificationMethod, Announcement, Certificate, CertificateStatus, User, StudentProfile
)
from routes.auth import organizer_required, get_current_user
from services.export_service import export_participants_excel, export_participants_csv
from services.event_service import delete_event_with_cleanup
from services.cert_upload_service import (
    process_certificate_uploads, manual_assign_certificate,
    resolve_duplicate_certificate, delete_single_certificate
)

organizer_bp = Blueprint('organizer', __name__, url_prefix='/organizer')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@organizer_bp.route('/dashboard')
@organizer_required
def dashboard():
    user = get_current_user()
    now = datetime.utcnow()

    # Organizer's events
    events = Event.query.filter_by(organizer_id=user.id).order_by(Event.created_at.desc()).all()
    event_ids = [e.id for e in events]

    total_events = len(events)
    active_events = len([e for e in events if e.status in (EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN)])
    pending_approval_events = len([e for e in events if e.status == EventStatus.PENDING_APPROVAL])
    completed_events_count = len([e for e in events if e.status == EventStatus.EVENT_COMPLETED])

    # Separate active vs completed events for clean dashboard display
    active_events_list = [e for e in events if e.status != EventStatus.EVENT_COMPLETED]
    completed_events_list = [e for e in events if e.status == EventStatus.EVENT_COMPLETED]

    # Registrations across all organizer events
    if event_ids:
        all_registrations = EventRegistration.query.filter(EventRegistration.event_id.in_(event_ids)).all()
    else:
        all_registrations = []

    total_registrations = len(all_registrations)
    paid_registrations = len([r for r in all_registrations if r.payment and r.payment.status == PaymentStatus.SUCCESS])
    confirmed_registrations = len([r for r in all_registrations if r.status == RegistrationStatus.CONFIRMED])
    pending_registrations = len([r for r in all_registrations if r.status == RegistrationStatus.PENDING_PAYMENT])
    attended_count = len([r for r in all_registrations if r.attendance is not None])

    # Recent 10 registrations
    recent_registrations = []
    if event_ids:
        recent_registrations = EventRegistration.query.filter(
            EventRegistration.event_id.in_(event_ids)
        ).order_by(EventRegistration.created_at.desc()).limit(10).all()

    return render_template(
        'organizer/dashboard.html',
        user=user,
        events=active_events_list,
        completed_events=completed_events_list,
        total_events=total_events,
        active_events=active_events,
        pending_approval_events=pending_approval_events,
        completed_events_count=completed_events_count,
        total_registrations=total_registrations,
        paid_registrations=paid_registrations,
        confirmed_registrations=confirmed_registrations,
        pending_registrations=pending_registrations,
        attended_count=attended_count,
        recent_registrations=recent_registrations
    )


@organizer_bp.route('/events/create', methods=['GET', 'POST'])
@organizer_required
def create_event():
    user = get_current_user()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        event_type = request.form.get('event_type', EventType.WORKSHOP)
        department = request.form.get('department', '').strip()
        faculty_coordinator = request.form.get('faculty_coordinator', '').strip()
        faculty_coordinator_contact = request.form.get('faculty_coordinator_contact', '').strip()
        contact_info = request.form.get('contact_info', '').strip()
        
        allowed_departments = request.form.get('allowed_departments', 'ALL').strip()
        allowed_years = request.form.get('allowed_years', 'ALL').strip()
        allowed_sections = request.form.get('allowed_sections', 'ALL').strip()
        eligibility_notes = request.form.get('eligibility_notes', '').strip()

        description = request.form.get('description', '').strip()
        rules = request.form.get('rules', '').strip()
        venue = request.form.get('venue', '').strip()

        start_time_str = request.form.get('start_time', '').strip()
        end_time_str = request.form.get('end_time', '').strip()
        deadline_str = request.form.get('registration_deadline', '').strip()

        max_participants = int(request.form.get('max_participants', 100))
        is_free = request.form.get('is_free') == 'true' or request.form.get('is_free') == 'on'
        registration_fee = 0.0 if is_free else float(request.form.get('registration_fee', 0.0))

        if not all([title, department, faculty_coordinator, venue, start_time_str, end_time_str, deadline_str, description]):
            flash('Please fill in all required event details.', 'danger')
            return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES)

        try:
            start_time = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
            end_time = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M')
            registration_deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')
        except ValueError:
            flash('Invalid date or time format.', 'danger')
            return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES)

        # Handle poster upload
        poster_path = None
        if 'poster' in request.files:
            file = request.files['poster']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"poster_{int(datetime.utcnow().timestamp())}_{file.filename}")
                upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'posters'
                upload_dir.mkdir(parents=True, exist_ok=True)
                file.save(upload_dir / filename)
                poster_path = f"uploads/posters/{filename}"

        slug = Event.generate_slug(title)

        event = Event(
            title=title,
            slug=slug,
            organizer_id=user.id,
            event_type=event_type,
            department=department,
            faculty_coordinator=faculty_coordinator,
            faculty_coordinator_contact=faculty_coordinator_contact,
            contact_info=contact_info,
            allowed_departments=allowed_departments or 'ALL',
            allowed_years=allowed_years or 'ALL',
            allowed_sections=allowed_sections or 'ALL',
            eligibility_notes=eligibility_notes,
            description=description,
            rules=rules,
            poster_image=poster_path,
            venue=venue,
            start_time=start_time,
            end_time=end_time,
            registration_deadline=registration_deadline,
            max_participants=max_participants,
            registration_fee=registration_fee,
            is_free=is_free,
            status=EventStatus.PENDING_APPROVAL
        )
        db.session.add(event)
        db.session.commit()

        flash('Event created successfully! It is now Pending Approval by Faculty/Admin.', 'success')
        return redirect(url_for('organizer.custom_fields', event_id=event.id))

    return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES)


@organizer_bp.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@organizer_required
def edit_event(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    if request.method == 'POST':
        event.title = request.form.get('title', event.title).strip()
        event.event_type = request.form.get('event_type', event.event_type)
        event.department = request.form.get('department', event.department).strip()
        event.faculty_coordinator = request.form.get('faculty_coordinator', event.faculty_coordinator).strip()
        event.faculty_coordinator_contact = request.form.get('faculty_coordinator_contact', '').strip()
        event.contact_info = request.form.get('contact_info', '').strip()

        event.allowed_departments = request.form.get('allowed_departments', 'ALL').strip()
        event.allowed_years = request.form.get('allowed_years', 'ALL').strip()
        event.allowed_sections = request.form.get('allowed_sections', 'ALL').strip()
        event.eligibility_notes = request.form.get('eligibility_notes', '').strip()

        event.description = request.form.get('description', event.description).strip()
        event.rules = request.form.get('rules', '').strip()
        event.venue = request.form.get('venue', event.venue).strip()

        start_time_str = request.form.get('start_time', '').strip()
        end_time_str = request.form.get('end_time', '').strip()
        deadline_str = request.form.get('registration_deadline', '').strip()

        if start_time_str:
            event.start_time = datetime.strptime(start_time_str, '%Y-%m-%dT%H:%M')
        if end_time_str:
            event.end_time = datetime.strptime(end_time_str, '%Y-%m-%dT%H:%M')
        if deadline_str:
            event.registration_deadline = datetime.strptime(deadline_str, '%Y-%m-%dT%H:%M')

        event.max_participants = int(request.form.get('max_participants', event.max_participants))
        is_free = request.form.get('is_free') == 'true' or request.form.get('is_free') == 'on'
        event.is_free = is_free
        event.registration_fee = 0.0 if is_free else float(request.form.get('registration_fee', 0.0))

        # Handle poster upload
        if 'poster' in request.files:
            file = request.files['poster']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"poster_{event.id}_{int(datetime.utcnow().timestamp())}_{file.filename}")
                upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'posters'
                upload_dir.mkdir(parents=True, exist_ok=True)
                file.save(upload_dir / filename)
                event.poster_image = f"uploads/posters/{filename}"

        db.session.commit()
        flash('Event updated successfully!', 'success')
        return redirect(url_for('organizer.manage_event', event_id=event.id))

    return render_template('organizer/edit_event.html', user=user, event=event, event_types=EventType.CHOICES)


@organizer_bp.route('/events/<int:event_id>/custom-fields', methods=['GET', 'POST'])
@organizer_required
def custom_fields(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            label = request.form.get('field_label', '').strip()
            field_type = request.form.get('field_type', 'text')
            is_required = request.form.get('is_required') == 'on'
            options_csv = request.form.get('options_csv', '').strip()

            if label:
                field_name = label.lower().replace(' ', '_').replace('-', '_')
                order = len(event.custom_fields) + 1
                new_field = CustomRegistrationField(
                    event_id=event.id,
                    field_name=field_name,
                    field_label=label,
                    field_type=field_type,
                    is_required=is_required,
                    options_csv=options_csv,
                    display_order=order
                )
                db.session.add(new_field)
                db.session.commit()
                flash(f"Custom field '{label}' added.", 'success')

        elif action == 'delete':
            field_id = request.form.get('field_id')
            field = CustomRegistrationField.query.filter_by(id=field_id, event_id=event.id).first()
            if field:
                db.session.delete(field)
                db.session.commit()
                flash('Custom field deleted.', 'info')

        return redirect(url_for('organizer.custom_fields', event_id=event.id))

    fields = event.custom_fields
    return render_template('organizer/custom_fields.html', user=user, event=event, fields=fields)


@organizer_bp.route('/events/<int:event_id>/manage')
@organizer_required
def manage_event(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    registrations = event.registrations.order_by(EventRegistration.created_at.desc()).all()
    confirmed_regs = [r for r in registrations if r.is_confirmed]
    attended_regs = [r for r in registrations if r.attendance is not None]
    total_revenue = sum([r.payment.amount for r in registrations if r.payment and r.payment.status == PaymentStatus.SUCCESS])

    return render_template(
        'organizer/event_manage.html',
        user=user,
        event=event,
        registrations=registrations,
        confirmed_count=len(confirmed_regs),
        attended_count=len(attended_regs),
        total_revenue=total_revenue
    )


@organizer_bp.route('/events/<int:event_id>/participants')
@organizer_required
def participants(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    # Search & filters
    search = request.args.get('q', '').strip()
    filter_dept = request.args.get('department', '').strip()
    filter_year = request.args.get('year', '').strip()
    filter_status = request.args.get('status', '').strip()
    filter_attendance = request.args.get('attendance', '').strip()

    query = EventRegistration.query.filter_by(event_id=event.id)

    if filter_status:
        query = query.filter_by(status=filter_status)

    registrations = query.order_by(EventRegistration.created_at.desc()).all()

    # In-memory filter for joined fields
    filtered_regs = []
    for r in registrations:
        student = r.student
        profile = student.student_profile

        if search:
            match_name = search.lower() in student.name.lower()
            match_email = search.lower() in student.email.lower()
            match_roll = profile and search.lower() in profile.roll_number.lower()
            match_code = search.lower() in r.registration_code.lower()
            if not (match_name or match_email or match_roll or match_code):
                continue

        if filter_dept and profile and profile.department != filter_dept:
            continue

        if filter_year and profile and str(profile.year) != filter_year:
            continue

        if filter_attendance == 'present' and not r.attendance:
            continue
        elif filter_attendance == 'absent' and r.attendance:
            continue

        filtered_regs.append(r)

    departments = ['CSE', 'IT', 'ECE', 'MECH', 'CIVIL', 'EEE']

    return render_template(
        'organizer/participants.html',
        user=user,
        event=event,
        registrations=filtered_regs,
        search=search,
        filter_dept=filter_dept,
        filter_year=filter_year,
        filter_status=filter_status,
        filter_attendance=filter_attendance,
        departments=departments
    )


@organizer_bp.route('/events/<int:event_id>/export/excel')
@organizer_required
def export_excel(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    registrations = event.registrations.all()
    excel_stream = export_participants_excel(event, registrations)

    filename = f"{event.slug}_participants.xlsx"
    return send_file(
        excel_stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )


@organizer_bp.route('/events/<int:event_id>/export/csv')
@organizer_required
def export_csv(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    registrations = event.registrations.all()
    csv_stream = export_participants_csv(event, registrations)

    filename = f"{event.slug}_participants.csv"
    return send_file(
        io.BytesIO(csv_stream.getvalue().encode('utf-8')),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


@organizer_bp.route('/events/<int:event_id>/scanner')
@organizer_required
def attendance_scanner(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    recent_attendance = AttendanceRecord.query.filter_by(event_id=event.id).order_by(AttendanceRecord.scanned_at.desc()).limit(15).all()

    return render_template(
        'organizer/attendance_scanner.html',
        user=user,
        event=event,
        recent_attendance=recent_attendance
    )


@organizer_bp.route('/attendance/mark', methods=['POST'])
@organizer_required
def mark_attendance():
    """
    AJAX endpoint called by live camera QR scanner or manual registration code input.
    """
    user = get_current_user()
    data = request.get_json() or {}
    raw_code = data.get('registration_code', '').strip()
    event_id = data.get('event_id')

    if not raw_code or not event_id:
        return jsonify({'status': 'error', 'message': 'Missing ticket code or event identifier.'}), 400

    # Parse raw code if it has the ticket prefix
    clean_code = raw_code.replace('FASTFEST-TICKET:', '').strip()

    registration = EventRegistration.query.filter_by(registration_code=clean_code).first()

    if not registration:
        return jsonify({'status': 'invalid', 'message': f"Ticket '{clean_code}' not found in system."}), 404

    if str(registration.event_id) != str(event_id):
        return jsonify({
            'status': 'mismatch',
            'message': f"This ticket belongs to '{registration.event.title}', not this event."
        }), 400

    if not registration.is_confirmed:
        return jsonify({
            'status': 'unconfirmed',
            'message': f"Registration is not confirmed (Status: {registration.status})."
        }), 400

    # Check for duplicate attendance
    existing_attendance = AttendanceRecord.query.filter_by(registration_id=registration.id).first()
    if existing_attendance:
        return jsonify({
            'status': 'duplicate',
            'message': f"Attendance already marked for {registration.student.name} at {existing_attendance.scanned_at.strftime('%I:%M %p')}.",
            'student_name': registration.student.name,
            'roll_number': registration.student.student_profile.roll_number if registration.student.student_profile else 'N/A',
            'department': registration.student.student_profile.department if registration.student.student_profile else 'N/A',
            'scanned_at': existing_attendance.scanned_at.strftime('%I:%M %p')
        }), 200

    # Mark attendance
    att_record = AttendanceRecord(
        registration_id=registration.id,
        event_id=registration.event_id,
        student_id=registration.student_id,
        marked_by_id=user.id,
        verification_method=VerificationMethod.QR_SCAN
    )
    db.session.add(att_record)
    db.session.commit()

    student_profile = registration.student.student_profile

    return jsonify({
        'status': 'success',
        'message': f"Attendance marked for {registration.student.name}!",
        'student_name': registration.student.name,
        'roll_number': student_profile.roll_number if student_profile else 'N/A',
        'department': student_profile.department if student_profile else 'N/A',
        'year': student_profile.year if student_profile else 'N/A',
        'section': student_profile.section if student_profile else 'N/A',
        'scanned_at': att_record.scanned_at.strftime('%I:%M %p')
    }), 200


@organizer_bp.route('/events/<int:event_id>/announcements', methods=['GET', 'POST'])
@organizer_required
def announcements(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        is_pinned = request.form.get('is_pinned') == 'on'

        if title and message:
            announcement = Announcement(
                event_id=event.id,
                author_id=user.id,
                title=title,
                message=message,
                is_pinned=is_pinned
            )
            db.session.add(announcement)
            db.session.commit()
            flash('Announcement published to all participants!', 'success')
            return redirect(url_for('organizer.announcements', event_id=event.id))
        else:
            flash('Title and message are required.', 'danger')

    announcement_list = event.announcements
    return render_template('organizer/announcements.html', user=user, event=event, announcements=announcement_list)


@organizer_bp.route('/events/<int:event_id>/certificates')
@organizer_required
def certificates(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    tab_filter = request.args.get('tab', 'all').strip().lower()

    # Query all certificates for this event
    all_certs = Certificate.query.filter_by(event_id=event.id).order_by(Certificate.created_at.desc()).all()

    # Filter by status tab if requested
    if tab_filter == 'matched':
        certs_list = [c for c in all_certs if c.status in (CertificateStatus.MATCHED, CertificateStatus.MANUALLY_ASSIGNED)]
    elif tab_filter == 'unmatched':
        certs_list = [c for c in all_certs if c.status == CertificateStatus.UNMATCHED]
    elif tab_filter == 'duplicate':
        certs_list = [c for c in all_certs if c.status == CertificateStatus.DUPLICATE]
    elif tab_filter == 'invalid':
        certs_list = [c for c in all_certs if c.status == CertificateStatus.INVALID]
    else:
        certs_list = all_certs

    # Statistics
    total_uploaded = len(all_certs)
    matched_count = len([c for c in all_certs if c.status in (CertificateStatus.MATCHED, CertificateStatus.MANUALLY_ASSIGNED)])
    unmatched_count = len([c for c in all_certs if c.status == CertificateStatus.UNMATCHED])
    duplicate_count = len([c for c in all_certs if c.status == CertificateStatus.DUPLICATE])
    invalid_count = len([c for c in all_certs if c.status == CertificateStatus.INVALID])

    # Registered students for manual assignment modal
    registrations = EventRegistration.query.filter_by(event_id=event.id).all()
    registered_students = [r.student for r in registrations if r.student]

    return render_template(
        'organizer/certificates.html',
        user=user,
        event=event,
        certificates=certs_list,
        total_uploaded=total_uploaded,
        matched_count=matched_count,
        unmatched_count=unmatched_count,
        duplicate_count=duplicate_count,
        invalid_count=invalid_count,
        tab_filter=tab_filter,
        registered_students=registered_students
    )


@organizer_bp.route('/events/<int:event_id>/certificates/upload', methods=['POST'])
@organizer_required
def upload_certificates(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    files = request.files.getlist('certificates')
    zip_file = request.files.get('zip_file')
    custom_pattern = request.form.get('custom_pattern', '').strip()

    if (not files or len(files) == 0 or not files[0].filename) and (not zip_file or not zip_file.filename):
        flash('Please select certificate files (PDF/Images) or a ZIP archive to upload.', 'danger')
        return redirect(url_for('organizer.certificates', event_id=event.id))

    # Process uploads, text extraction, OCR, roll number extraction & student matching
    report = process_certificate_uploads(
        event_id=event.id,
        files_list=files,
        zip_file=zip_file,
        custom_pattern=custom_pattern or None,
        uploader_user=user
    )

    total = report['total_uploaded']
    matched = report['matched']
    unmatched = report['unmatched']
    dup = report['duplicate']
    inv = report['invalid']

    if total > 0:
        msg = f"Processed {total} certificate(s): {matched} automatically matched with students"
        if unmatched > 0:
            msg += f", {unmatched} unmatched"
        if dup > 0:
            msg += f", {dup} duplicate"
        if inv > 0:
            msg += f", {inv} invalid"
        msg += "."
        flash(msg, 'success' if unmatched == 0 and dup == 0 else 'info')
    else:
        flash("No valid certificate files found in the upload.", 'warning')

    return redirect(url_for('organizer.certificates', event_id=event.id))


@organizer_bp.route('/events/<int:event_id>/certificates/<int:cert_id>/assign', methods=['POST'])
@organizer_required
def assign_certificate(event_id, cert_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    student_id = request.form.get('student_id')
    manual_roll = request.form.get('roll_number', '').strip()

    if not student_id:
        flash('Please select a student to assign the certificate.', 'danger')
        return redirect(url_for('organizer.certificates', event_id=event.id, tab='unmatched'))

    try:
        cert = manual_assign_certificate(
            cert_id=cert_id,
            student_id=int(student_id),
            roll_number=manual_roll or None,
            assigned_by_user=user
        )
        flash(f"Certificate '{cert.original_filename}' successfully assigned to {cert.student.name} ({cert.roll_number})!", 'success')
    except Exception as e:
        flash(f"Error assigning certificate: {str(e)}", 'danger')

    return redirect(url_for('organizer.certificates', event_id=event.id))


@organizer_bp.route('/events/<int:event_id>/certificates/<int:cert_id>/resolve-duplicate', methods=['POST'])
@organizer_required
def resolve_duplicate(event_id, cert_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    action = request.form.get('action') # 'replace', 'keep_both', 'discard'

    if action in ('replace', 'keep_both', 'discard'):
        result = resolve_duplicate_certificate(cert_id=cert_id, action=action, current_user=user)
        if result == 'replaced':
            flash('Existing certificate was replaced with this uploaded version.', 'success')
        elif result == 'kept_both':
            flash('Certificate marked as active alongside existing.', 'info')
        elif result == 'discarded':
            flash('Duplicate certificate discarded and removed.', 'info')

    return redirect(url_for('organizer.certificates', event_id=event.id, tab='duplicate'))


@organizer_bp.route('/events/<int:event_id>/certificates/<int:cert_id>/delete', methods=['POST'])
@organizer_required
def delete_certificate(event_id, cert_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    delete_single_certificate(cert_id)
    flash('Certificate deleted successfully.', 'info')
    return redirect(url_for('organizer.certificates', event_id=event.id))


@organizer_bp.route('/certificates/<int:cert_id>/download')
@organizer_required
def download_certificate(cert_id):
    user = get_current_user()
    cert = Certificate.query.get_or_404(cert_id)

    if cert.event.organizer_id != user.id and not user.is_admin:
        abort(403)

    full_path = Path(__file__).resolve().parent.parent / 'static' / cert.file_path
    if not full_path.exists():
        abort(404)

    return send_file(
        str(full_path),
        as_attachment=True,
        download_name=cert.original_filename
    )


@organizer_bp.route('/certificates/<int:cert_id>/preview')
@organizer_required
def preview_certificate(cert_id):
    user = get_current_user()
    cert = Certificate.query.get_or_404(cert_id)

    if cert.event.organizer_id != user.id and not user.is_admin:
        abort(403)

    full_path = Path(__file__).resolve().parent.parent / 'static' / cert.file_path
    if not full_path.exists():
        abort(404)

    mimetype = 'application/pdf' if cert.is_pdf else 'image/png'
    return send_file(
        str(full_path),
        mimetype=mimetype,
        as_attachment=False
    )


@organizer_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@organizer_required
def delete_event(event_id):
    from services.event_service import are_certificates_completed
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    if not are_certificates_completed(event):
        flash(f"Cannot delete event '{event.title}': Certificate submission to attending students is not yet completed. Please issue all certificates before deleting.", 'danger')
        return redirect(url_for('organizer.manage_event', event_id=event.id))

    title = event.title
    delete_event_with_cleanup(event)
    db.session.commit()
    flash(f"Event '{title}' has been successfully deleted.", 'success')
    return redirect(url_for('organizer.dashboard'))


@organizer_bp.route('/events/<int:event_id>/complete', methods=['POST'])
@organizer_required
def complete_event(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    event.status = EventStatus.EVENT_COMPLETED
    db.session.commit()
    flash(f"Event '{event.title}' has been marked as Completed. Active passes and registrations are archived, while all certificates and attendance records are safely preserved.", 'success')
    return redirect(url_for('organizer.manage_event', event_id=event.id))



