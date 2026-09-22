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
    AttendanceRecord, VerificationMethod, AttendanceStatus, AttendanceSession, AttendanceSessionStatus,
    Announcement, Certificate, CertificateStatus, User, StudentProfile, OrganizerProfile,
    Team, TeamStatus, TeamPaymentStatus, TeamRole, TeamMemberStatus, InvitationStatus, TeamMember, TeamInvitation,
    EventRegistrationType, TeamPaymentType, CollegeDepartment,
    EventRequest, EventRequestStatus, NotificationType
)
from routes.auth import organizer_required, get_current_user
from services.export_service import export_participants_excel, export_participants_csv
from services.event_service import delete_event_with_cleanup, delete_expired_events
from services.notification_service import create_notification
from services.email_service import send_event_request_submitted_email
from services.attendance_service import (
    create_or_update_event_sessions, record_session_attendance,
    manual_override_attendance, calculate_event_attendance_matrix,
    AttendanceServiceError
)
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
    tab = request.args.get('tab', 'requests').strip().lower()

    # Organizer's Event Requests (Full Dual Approval Lifecycle)
    event_requests = EventRequest.query.filter_by(organizer_id=user.id).order_by(EventRequest.created_at.desc()).all()
    pending_hod_requests = [r for r in event_requests if r.overall_status == EventRequestStatus.PENDING_HOD_APPROVAL]
    forwarded_requests = [r for r in event_requests if r.overall_status == EventRequestStatus.PENDING_DEAN_APPROVAL]
    approved_requests = [r for r in event_requests if r.overall_status == EventRequestStatus.APPROVED]
    rejected_requests = [r for r in event_requests if r.overall_status in (EventRequestStatus.REJECTED_BY_HOD, EventRequestStatus.REJECTED_BY_DEAN)]

    # Published and Approved Events for operational management
    all_events = Event.query.filter_by(organizer_id=user.id, is_published=True).order_by(Event.created_at.desc()).all()
    event_ids = [e.id for e in all_events]

    active_events_list = [e for e in all_events if not e.is_completed and e.status != EventStatus.CANCELLED]
    completed_events_list = [e for e in all_events if e.is_completed]

    total_events = len(all_events)
    active_events_count = len(active_events_list)
    completed_events_count = len(completed_events_list)

    # Select events based on active tab
    if tab == 'completed':
        displayed_events = completed_events_list
    elif tab == 'all_published':
        displayed_events = all_events
    else:
        displayed_events = active_events_list

    # Registrations across all published events
    if event_ids:
        all_registrations = EventRegistration.query.filter(EventRegistration.event_id.in_(event_ids)).all()
    else:
        all_registrations = []

    total_registrations = len(all_registrations)
    paid_registrations = len([r for r in all_registrations if r.payment and r.payment.status in (PaymentStatus.VERIFIED, 'SUCCESS')])
    confirmed_registrations = len([r for r in all_registrations if r.status == RegistrationStatus.CONFIRMED])
    pending_registrations = len([r for r in all_registrations if r.status == RegistrationStatus.PENDING_PAYMENT])
    attended_count = len([r for r in all_registrations if r.attendance is not None])

    # Pending payment verifications for organizer's events (including verified transaction IDs awaiting organizer approval)
    pending_payments = []
    if event_ids:
        pending_payments = Payment.query.filter(
            Payment.event_id.in_(event_ids),
            Payment.status.in_([PaymentStatus.PENDING, PaymentStatus.MANUAL_REVIEW, PaymentStatus.TRANSACTION_ID_VERIFIED])
        ).order_by(Payment.submitted_at.desc()).all()

    # Recent 10 registrations
    recent_registrations = []
    if event_ids:
        recent_registrations = EventRegistration.query.filter(
            EventRegistration.event_id.in_(event_ids)
        ).order_by(EventRegistration.created_at.desc()).limit(10).all()

    return render_template(
        'organizer/dashboard.html',
        user=user,
        events=displayed_events,
        total_events=total_events,
        active_events=active_events_count,
        completed_events_count=completed_events_count,
        event_requests=event_requests,
        pending_hod_requests=pending_hod_requests,
        forwarded_requests=forwarded_requests,
        approved_requests=approved_requests,
        rejected_requests=rejected_requests,
        total_registrations=total_registrations,
        paid_registrations=paid_registrations,
        confirmed_registrations=confirmed_registrations,
        pending_registrations=pending_registrations,
        attended_count=attended_count,
        recent_registrations=recent_registrations,
        pending_payments=pending_payments,
        current_tab=tab
    )


@organizer_bp.route('/events/create', methods=['GET', 'POST'])
@organizer_bp.route('/events/request', methods=['GET', 'POST'])
@organizer_required
def create_event():
    user = get_current_user()

    # Automatically resolve Organizer's department from profile
    # The Organizer must NOT manually submit an event for another department
    dept_code = 'CSE'
    if user.organizer_profile and user.organizer_profile.department:
        dept_code = user.organizer_profile.department
    elif user.student_profile and user.student_profile.department:
        dept_code = user.student_profile.department

    dept_obj = CollegeDepartment.query.filter_by(code=dept_code).first()
    if not dept_obj:
        dept_obj = CollegeDepartment.query.first()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        event_type = request.form.get('event_type', EventType.WORKSHOP)
        venue = request.form.get('venue', '').strip()
        description = request.form.get('description', '').strip()
        rules = request.form.get('rules', '').strip()
        budget_requirements = request.form.get('budget_requirements', '').strip()
        additional_requirements = request.form.get('additional_requirements', '').strip()
        
        faculty_coordinator = request.form.get('faculty_coordinator', '').strip()
        faculty_coordinator_contact = request.form.get('faculty_coordinator_contact', '').strip()
        contact_info = request.form.get('contact_info', '').strip()

        allowed_departments = request.form.get('allowed_departments', 'ALL').strip()
        allowed_years = request.form.get('allowed_years', 'ALL').strip()
        allowed_sections = request.form.get('allowed_sections', 'ALL').strip()
        eligibility_notes = request.form.get('eligibility_notes', '').strip()

        reg_start_str = request.form.get('registration_start_date', '').strip()
        deadline_str = request.form.get('registration_deadline', '').strip()
        start_time_str = request.form.get('start_time', '').strip()
        end_time_str = request.form.get('end_time', '').strip()

        max_participants = int(request.form.get('max_participants', 100))
        is_free = request.form.get('is_free') == 'true' or request.form.get('is_free') == 'on'
        registration_fee = 0.0 if is_free else float(request.form.get('registration_fee', 0.0))

        # Attendance Configuration
        enable_attendance = request.form.get('enable_attendance') != 'false' and request.form.get('enable_attendance') is not None
        min_attendance_percentage = float(request.form.get('min_attendance_percentage') or 0.0)

        # Team Registration Settings
        registration_type = request.form.get('registration_type', EventRegistrationType.INDIVIDUAL)
        min_team_size = int(request.form.get('min_team_size', 2))
        max_team_size = int(request.form.get('max_team_size', 4))
        team_payment_type = request.form.get('team_payment_type', TeamPaymentType.FREE)
        require_full_team = request.form.get('require_full_team') == 'true' or request.form.get('require_full_team') == 'on'

        if not all([title, venue, start_time_str, end_time_str, description]):
            flash('Please fill in all required event proposal fields.', 'danger')
            return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES, dept_obj=dept_obj)

        from services.timezone_service import parse_form_datetime, to_ist
        start_time = parse_form_datetime(start_time_str)
        end_time = parse_form_datetime(end_time_str)
        registration_deadline = parse_form_datetime(deadline_str) if deadline_str else start_time
        registration_start_date = parse_form_datetime(reg_start_str) if reg_start_str else datetime.utcnow()

        if not all([start_time, end_time, registration_deadline]):
            flash('Invalid date or time format. Please verify your schedule entries.', 'danger')
            return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES, dept_obj=dept_obj)

        # Chronological validation
        if registration_start_date >= registration_deadline:
            flash('Registration start date/time must be earlier than the registration deadline.', 'danger')
            return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES, dept_obj=dept_obj)

        if registration_deadline > start_time:
            flash('Registration deadline must be before or equal to the event start time.', 'danger')
            return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES, dept_obj=dept_obj)

        if start_time >= end_time:
            flash('Event start time must be before event end time.', 'danger')
            return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES, dept_obj=dept_obj)

        # Handle UPI & QR upload for paid events
        upi_id = request.form.get('upi_id', '').strip()
        upi_number = request.form.get('upi_number', '').strip()
        payment_instructions = request.form.get('payment_instructions', '').strip()

        upi_qr_path = None
        if 'upi_qr' in request.files:
            qr_file = request.files['upi_qr']
            if qr_file and allowed_file(qr_file.filename):
                qr_filename = secure_filename(f"upi_qr_{int(datetime.utcnow().timestamp())}_{qr_file.filename}")
                qr_upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'organizer_qrs'
                qr_upload_dir.mkdir(parents=True, exist_ok=True)
                qr_file.save(qr_upload_dir / qr_filename)
                upi_qr_path = f"uploads/organizer_qrs/{qr_filename}"

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

        # MANDATORY: Create EventRequest with status PENDING_HOD_APPROVAL
        # The organizer must NEVER directly publish an event!
        event_req = EventRequest(
            organizer_id=user.id,
            department_id=dept_obj.id,
            event_name=title,
            description=description,
            category=event_type,
            proposed_event_date=to_ist(start_time).date(),
            start_time=start_time,
            end_time=end_time,
            venue=venue,
            expected_participants=max_participants,
            registration_details=f"Type: {registration_type} | Fee: ₹{registration_fee}",
            budget_requirements=budget_requirements,
            additional_requirements=additional_requirements,
            registration_start_date=registration_start_date,
            registration_deadline=registration_deadline,
            registration_fee=registration_fee,
            is_free=is_free,
            poster_image=poster_path,
            rules=rules,
            contact_info=contact_info,
            faculty_coordinator=faculty_coordinator,
            faculty_coordinator_contact=faculty_coordinator_contact,
            allowed_departments=allowed_departments or 'ALL',
            allowed_years=allowed_years or 'ALL',
            allowed_sections=allowed_sections or 'ALL',
            eligibility_notes=eligibility_notes,
            registration_type=registration_type,
            min_team_size=min_team_size,
            max_team_size=max_team_size,
            team_payment_type=team_payment_type,
            require_full_team=require_full_team,
            upi_id=upi_id,
            upi_number=upi_number,
            upi_qr_image=upi_qr_path,
            payment_instructions=payment_instructions,
            enable_attendance=enable_attendance,
            min_attendance_percentage=min_attendance_percentage,
            overall_status=EventRequestStatus.PENDING_HOD_APPROVAL
        )
        db.session.add(event_req)
        db.session.commit()

        # Step 1 Routing: Route strictly to assigned Department HOD
        hod_user = dept_obj.hod
        if hod_user:
            create_notification(
                user_id=hod_user.id,
                title=f"New Event Proposal: {title}",
                message=f"Organizer {user.name} submitted an event creation request '{title}' for your departmental review.",
                notification_type=NotificationType.EVENT_REQUEST,
                link=url_for('hod.event_request_detail', request_id=event_req.id)
            )
            try:
                send_event_request_submitted_email(event_req, user, hod_user, dept_obj)
            except Exception as em_err:
                current_app.logger.warning(f"Could not dispatch HOD event request email: {em_err}")

        # Send Confirmation Email & In-App Notification to Organizer
        try:
            from services.email_service import send_event_request_submitted_organizer_confirm_email
            create_notification(
                user_id=user.id,
                title=f"Event Proposal Submitted: {title}",
                message=f"Your event proposal '{title}' was submitted and forwarded to HOD {hod_user.name if hod_user else 'your department'} for initial review.",
                notification_type=NotificationType.EVENT_REQUEST,
                link=url_for('organizer.dashboard', tab='requests')
            )
            send_event_request_submitted_organizer_confirm_email(event_req, user, hod_user, dept_obj)
        except Exception as em_err:
            current_app.logger.warning(f"Could not dispatch organizer proposal submission email: {em_err}")

        flash(
            f"Event proposal '{title}' submitted successfully! It has been forwarded to your Department HOD ({dept_obj.name}) for initial review. Once approved, it will proceed to the Students Affairs Dean for final college-level publication clearance.",
            'success'
        )
        return redirect(url_for('organizer.dashboard', tab='requests'))

    return render_template('organizer/create_event.html', user=user, event_types=EventType.CHOICES, dept_obj=dept_obj)


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

        reg_start_str = request.form.get('registration_start_date', '').strip()
        deadline_str = request.form.get('registration_deadline', '').strip()
        start_time_str = request.form.get('start_time', '').strip()
        end_time_str = request.form.get('end_time', '').strip()

        from services.timezone_service import parse_form_datetime
        new_reg_start = parse_form_datetime(reg_start_str) if reg_start_str else event.registration_start_date
        new_deadline = parse_form_datetime(deadline_str) if deadline_str else event.registration_deadline
        new_start_time = parse_form_datetime(start_time_str) if start_time_str else event.start_time
        new_end_time = parse_form_datetime(end_time_str) if end_time_str else event.end_time

        # Validate schedule chronology if dates are set
        if new_reg_start and new_deadline and new_reg_start >= new_deadline:
            flash('Registration start date/time must be earlier than the registration deadline.', 'danger')
            return redirect(url_for('organizer.edit_event', event_id=event.id))

        if new_deadline and new_start_time and new_deadline > new_start_time:
            flash('Registration deadline must be before or equal to the event start time.', 'danger')
            return redirect(url_for('organizer.edit_event', event_id=event.id))

        if new_start_time and new_end_time and new_start_time >= new_end_time:
            flash('Event start time must be before event end time.', 'danger')
            return redirect(url_for('organizer.edit_event', event_id=event.id))

        if reg_start_str and new_reg_start:
            event.registration_start_date = new_reg_start
        if deadline_str and new_deadline:
            event.registration_deadline = new_deadline
        if start_time_str and new_start_time:
            event.start_time = new_start_time
        if end_time_str and new_end_time:
            event.end_time = new_end_time

        event.max_participants = int(request.form.get('max_participants', event.max_participants))
        is_free = request.form.get('is_free') == 'true' or request.form.get('is_free') == 'on'
        event.is_free = is_free
        event.registration_fee = 0.0 if is_free else float(request.form.get('registration_fee', 0.0))

        # Multi-Session Attendance Configuration
        event.enable_attendance = request.form.get('enable_attendance') == 'true' or request.form.get('enable_attendance') == 'on'
        event.min_attendance_percentage = float(request.form.get('min_attendance_percentage') or 0.0)

        # Team Registration Settings
        event.registration_type = request.form.get('registration_type', event.registration_type)
        event.min_team_size = int(request.form.get('min_team_size', event.min_team_size or 2))
        event.max_team_size = int(request.form.get('max_team_size', event.max_team_size or 4))
        event.team_payment_type = request.form.get('team_payment_type', event.team_payment_type or 'FREE')
        event.require_full_team = request.form.get('require_full_team') == 'true' or request.form.get('require_full_team') == 'on'

        # Update Sessions if provided
        session_names = request.form.getlist('session_names[]')
        session_dates = request.form.getlist('session_dates[]')
        session_start_times = request.form.getlist('session_start_times[]')
        session_end_times = request.form.getlist('session_end_times[]')
        session_ids = request.form.getlist('session_ids[]')

        if session_names:
            session_list = []
            for idx, sname in enumerate(session_names):
                if sname.strip():
                    session_list.append({
                        'id': session_ids[idx] if idx < len(session_ids) and session_ids[idx] else None,
                        'session_name': sname.strip(),
                        'event_date': session_dates[idx] if idx < len(session_dates) else None,
                        'start_time': session_start_times[idx] if idx < len(session_start_times) else None,
                        'end_time': session_end_times[idx] if idx < len(session_end_times) else None
                    })
            create_or_update_event_sessions(event, session_list)

        # Handle organizer UPI & QR upload for paid events
        event.upi_id = request.form.get('upi_id', event.upi_id or '').strip()
        event.upi_number = request.form.get('upi_number', event.upi_number or '').strip()
        event.payment_instructions = request.form.get('payment_instructions', event.payment_instructions or '').strip()

        if 'upi_qr' in request.files:
            qr_file = request.files['upi_qr']
            if qr_file and allowed_file(qr_file.filename):
                qr_filename = secure_filename(f"upi_qr_{event.id}_{int(datetime.utcnow().timestamp())}_{qr_file.filename}")
                qr_upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'organizer_qrs'
                qr_upload_dir.mkdir(parents=True, exist_ok=True)
                qr_file.save(qr_upload_dir / qr_filename)
                event.upi_qr_image = f"uploads/organizer_qrs/{qr_filename}"

        # Handle poster upload
        if 'poster' in request.files:
            file = request.files['poster']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"poster_{event.id}_{int(datetime.utcnow().timestamp())}_{file.filename}")
                upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'posters'
                upload_dir.mkdir(parents=True, exist_ok=True)
                file.save(upload_dir / filename)
                event.poster_image = f"uploads/posters/{filename}"

        # Sync associated EventRequest record if present
        if hasattr(event, 'creation_request') and event.creation_request:
            req = event.creation_request
            req.event_name = event.title
            req.description = event.description
            req.category = event.event_type
            req.venue = event.venue
            req.start_time = event.start_time
            req.end_time = event.end_time
            req.registration_start_date = event.registration_start_date
            req.registration_deadline = event.registration_deadline
            req.expected_participants = event.max_participants
            req.registration_fee = event.registration_fee
            req.is_free = event.is_free

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
    total_revenue = sum([r.payment.amount for r in registrations if r.payment and r.payment.status in (PaymentStatus.VERIFIED, 'SUCCESS')])
    
    # Also sum team payments
    team_revenue = sum([p.amount for p in Payment.query.join(Team).filter(Team.event_id == event.id, Payment.status.in_([PaymentStatus.VERIFIED, 'SUCCESS'])).all()])
    total_revenue += team_revenue

    teams = event.teams.all()
    total_teams_count = len(teams)
    complete_teams_count = len([t for t in teams if t.status in (TeamStatus.COMPLETE, TeamStatus.FULL)])
    pending_teams_count = len([t for t in teams if t.status == TeamStatus.PENDING])
    full_teams_count = len([t for t in teams if t.status == TeamStatus.FULL])

    return render_template(
        'organizer/event_manage.html',
        user=user,
        event=event,
        registrations=registrations,
        confirmed_count=len(confirmed_regs),
        attended_count=len(attended_regs),
        total_revenue=total_revenue,
        teams=teams,
        total_teams_count=total_teams_count,
        complete_teams_count=complete_teams_count,
        pending_teams_count=pending_teams_count,
        full_teams_count=full_teams_count
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
    filter_team_id = request.args.get('team_id', '').strip()

    query = EventRegistration.query.filter_by(event_id=event.id)

    if filter_status:
        query = query.filter_by(status=filter_status)

    if filter_team_id:
        try:
            query = query.filter_by(team_id=int(filter_team_id))
        except ValueError:
            pass

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
            match_team = r.team and search.lower() in r.team.team_name.lower()
            if not (match_name or match_email or match_roll or match_code or match_team):
                continue

        if filter_dept and profile:
            student_dept = (profile.department or '').strip().upper()
            filter_dept_upper = filter_dept.strip().upper()
            dept_matches = (student_dept == filter_dept_upper) or \
                           (student_dept in ['CIVIL', 'CIVILS'] and filter_dept_upper in ['CIVIL', 'CIVILS'])
            if not dept_matches:
                continue

        if filter_year and profile and str(profile.year) != filter_year:
            continue

        if filter_attendance == 'present' and not r.attendance:
            continue
        elif filter_attendance == 'absent' and r.attendance:
            continue

        filtered_regs.append(r)

    departments = ['CSE', 'IT', 'CSD', 'CSM', 'ECE', 'EEE', 'MECH', 'CIVILS']
    teams = event.teams.all()

    return render_template(
        'organizer/participants.html',
        user=user,
        event=event,
        registrations=filtered_regs,
        teams=teams,
        search=search,
        filter_dept=filter_dept,
        filter_year=filter_year,
        filter_status=filter_status,
        filter_attendance=filter_attendance,
        filter_team_id=filter_team_id,
        departments=departments
    )


@organizer_bp.route('/events/<int:event_id>/teams')
@organizer_required
def event_teams(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    teams = event.teams.order_by(Team.created_at.desc()).all()
    return render_template(
        'organizer/teams.html',
        user=user,
        event=event,
        teams=teams
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

    sessions = event.attendance_sessions.all()
    if not sessions and event.enable_attendance:
        # Create default session if none exists
        default_session = AttendanceSession(
            event_id=event.id,
            session_name="General Attendance",
            session_number=1,
            status=AttendanceSessionStatus.ACTIVE
        )
        db.session.add(default_session)
        db.session.commit()
        sessions = [default_session]

    # Select active session
    selected_session_id = request.args.get('session_id')
    selected_session = None
    if selected_session_id:
        selected_session = AttendanceSession.query.filter_by(id=int(selected_session_id), event_id=event.id).first()
    if not selected_session and sessions:
        selected_session = sessions[0]

    # Recent check-ins for the selected session
    recent_query = AttendanceRecord.query.filter_by(event_id=event.id)
    if selected_session:
        recent_query = recent_query.filter_by(session_id=selected_session.id)
    recent_attendance = recent_query.order_by(AttendanceRecord.scanned_at.desc()).limit(15).all()

    total_participants = event.confirmed_registrations_count
    present_count = selected_session.present_count if selected_session else 0

    return render_template(
        'organizer/attendance_scanner.html',
        user=user,
        event=event,
        sessions=sessions,
        selected_session=selected_session,
        recent_attendance=recent_attendance,
        total_participants=total_participants,
        present_count=present_count
    )


@organizer_bp.route('/attendance/mark', methods=['POST'])
@organizer_required
def mark_attendance():
    """
    AJAX endpoint called by live camera QR scanner or manual registration code input.
    Supports multi-session event attendance.
    """
    user = get_current_user()
    data = request.get_json() or {}
    raw_code = str(data.get('registration_code', '')).strip()
    event_id = data.get('event_id')
    session_id = data.get('session_id')
    allow_time_override = bool(data.get('allow_time_override', False))

    if not raw_code or not event_id:
        return jsonify({'status': 'error', 'message': 'Missing ticket code or event identifier.'}), 400

    try:
        parsed_event_id = int(event_id)
    except (ValueError, TypeError):
        return jsonify({'status': 'error', 'message': 'Invalid event identifier.'}), 400

    parsed_session_id = None
    if session_id is not None and str(session_id).strip() != '' and str(session_id).strip().lower() != 'none':
        try:
            parsed_session_id = int(session_id)
        except (ValueError, TypeError):
            parsed_session_id = None

    response_dict, status_code = record_session_attendance(
        event_id=parsed_event_id,
        session_id=parsed_session_id,
        registration_code=raw_code,
        marked_by_user=user,
        allow_time_override=allow_time_override
    )

    return jsonify(response_dict), status_code


@organizer_bp.route('/events/<int:event_id>/attendance')
@organizer_required
def attendance_dashboard(event_id):
    """
    Complete Participant x Attendance Session Matrix view for event organizers.
    """
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    matrix_data = calculate_event_attendance_matrix(event)
    teams = event.teams.all()

    return render_template(
        'organizer/attendance_dashboard.html',
        user=user,
        event=event,
        sessions=matrix_data['sessions'],
        matrix=matrix_data['matrix'],
        total_participants=matrix_data['total_participants'],
        teams=teams,
        min_attendance_percentage=event.min_attendance_percentage
    )


@organizer_bp.route('/events/<int:event_id>/attendance/manual', methods=['POST'])
@organizer_required
def manual_attendance(event_id):
    """
    Organizer manual override to mark student present or absent for a session.
    """
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    session_id = request.form.get('session_id')
    student_id = request.form.get('student_id')
    status = request.form.get('status', 'PRESENT').strip().upper()
    remarks = request.form.get('remarks', '').strip()

    if not session_id or not student_id:
        flash('Missing session or student information.', 'danger')
        return redirect(url_for('organizer.attendance_dashboard', event_id=event.id))

    try:
        manual_override_attendance(
            event_id=event.id,
            session_id=int(session_id),
            student_id=int(student_id),
            new_status=status,
            marked_by_user=user,
            remarks=remarks
        )
        flash(f'Attendance manually updated to {status} successfully.', 'success')
    except Exception as e:
        flash(f'Failed to update attendance: {str(e)}', 'danger')

    return redirect(url_for('organizer.attendance_dashboard', event_id=event.id))


@organizer_bp.route('/events/<int:event_id>/attendance/export/csv')
@organizer_required
def export_attendance_csv(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    registrations = event.registrations.all()
    csv_stream = export_participants_csv(event, registrations)

    filename = f"{event.slug}_attendance_matrix.csv"
    return send_file(
        io.BytesIO(csv_stream.getvalue().encode('utf-8')),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename
    )


@organizer_bp.route('/events/<int:event_id>/attendance/export/excel')
@organizer_required
def export_attendance_excel(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    registrations = event.registrations.all()
    excel_stream = export_participants_excel(event, registrations)

    filename = f"{event.slug}_attendance_matrix.xlsx"
    return send_file(
        excel_stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )


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
    if tab_filter in ('matched', 'matched_automatically'):
        certs_list = [c for c in all_certs if c.status in (CertificateStatus.MATCHED_AUTOMATICALLY, 'MATCHED')]
    elif tab_filter in ('pending', 'pending_manual_review'):
        certs_list = [c for c in all_certs if c.status == CertificateStatus.PENDING_MANUAL_REVIEW]
    elif tab_filter == 'unmatched':
        certs_list = [c for c in all_certs if c.status == CertificateStatus.UNMATCHED]
    elif tab_filter in ('assigned_manually', 'manual', 'manually_assigned'):
        certs_list = [c for c in all_certs if c.status in (CertificateStatus.ASSIGNED_MANUALLY, 'MANUALLY_ASSIGNED')]
    elif tab_filter == 'duplicate':
        certs_list = [c for c in all_certs if c.status == CertificateStatus.DUPLICATE]
    elif tab_filter == 'invalid':
        certs_list = [c for c in all_certs if c.status == CertificateStatus.INVALID]
    else:
        certs_list = all_certs

    # Statistics
    total_uploaded = len(all_certs)
    matched_count = len([c for c in all_certs if c.status in (CertificateStatus.MATCHED_AUTOMATICALLY, 'MATCHED')])
    pending_count = len([c for c in all_certs if c.status == CertificateStatus.PENDING_MANUAL_REVIEW])
    unmatched_count = len([c for c in all_certs if c.status == CertificateStatus.UNMATCHED])
    assigned_manually_count = len([c for c in all_certs if c.status in (CertificateStatus.ASSIGNED_MANUALLY, 'MANUALLY_ASSIGNED')])
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
        pending_count=pending_count,
        unmatched_count=unmatched_count,
        assigned_manually_count=assigned_manually_count,
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
    pending = report.get('pending', 0)
    unmatched = report['unmatched']
    dup = report['duplicate']
    inv = report['invalid']

    if total > 0:
        msg = f"Processed {total} certificate(s): {matched} automatically matched with registered students"
        if pending > 0:
            msg += f", {pending} pending manual review"
        if unmatched > 0:
            msg += f", {unmatched} unmatched"
        if dup > 0:
            msg += f", {dup} duplicate"
        if inv > 0:
            msg += f", {inv} invalid"
        msg += "."
        flash(msg, 'success' if unmatched == 0 and dup == 0 and pending == 0 else 'info')
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


@organizer_bp.route('/events/<int:event_id>/complete', methods=['POST'])
@organizer_required
def complete_event(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if event.organizer_id != user.id and not user.is_admin:
        abort(403)

    event.status = EventStatus.EVENT_COMPLETED
    # Purge broadcasts for completed/expired event
    Announcement.query.filter_by(event_id=event.id).delete()
    db.session.commit()
    flash(f"Event '{event.title}' has been marked as completed and removed from active dashboard.", 'info')
    return redirect(url_for('organizer.dashboard', tab='completed'))


@organizer_bp.route('/events/delete-completed', methods=['POST'])
@organizer_required
def delete_completed_events():
    user = get_current_user()
    count, deleted_titles, skipped_titles = delete_expired_events(require_certificates_done=True, organizer_id=user.id)

    if count > 0:
        flash(f"Successfully deleted {count} completed event(s) from your dashboard.", 'success')
    elif skipped_titles:
        flash(f"Retained {len(skipped_titles)} completed event(s) because certificate issuance to attendees is not yet completed.", 'warning')
    else:
        flash("No completed events eligible for deletion.", 'info')

    if skipped_titles and count > 0:
        flash(f"{len(skipped_titles)} event(s) were retained because certificates are still pending.", 'info')

    return redirect(url_for('organizer.dashboard', tab='active'))


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


# ==============================================================================
# PAYMENT VERIFICATION MANAGEMENT
# ==============================================================================

@organizer_bp.route('/payments/verification')
@organizer_required
def payment_verification():
    """
    Dedicated Payment Verification view showing all payments submitted for organizer's events.
    """
    user = get_current_user()
    my_events = Event.query.filter_by(organizer_id=user.id).all()
    event_ids = [e.id for e in my_events]

    filter_status = request.args.get('status', '').strip().upper()
    filter_event_id = request.args.get('event_id', '').strip()

    if not event_ids:
        payments = []
    else:
        query = Payment.query.filter(Payment.event_id.in_(event_ids))
        if filter_status:
            query = query.filter(Payment.status == filter_status)
        if filter_event_id:
            try:
                ev_id_int = int(filter_event_id)
                if ev_id_int in event_ids:
                    query = query.filter(Payment.event_id == ev_id_int)
            except ValueError:
                pass
        payments = query.order_by(Payment.submitted_at.desc()).all()

    # Detect duplicate transaction IDs within the same event
    from services.payment_verification_service import normalize_transaction_id
    txn_counts = {}
    for p in payments:
        norm_id = normalize_transaction_id(p.transaction_id)
        if norm_id and len(norm_id) >= 5:
            key = (p.event_id, norm_id)
            txn_counts[key] = txn_counts.get(key, 0) + 1

    duplicate_payment_ids = set()
    for p in payments:
        norm_id = normalize_transaction_id(p.transaction_id)
        if norm_id and len(norm_id) >= 5:
            key = (p.event_id, norm_id)
            if txn_counts.get(key, 0) > 1:
                duplicate_payment_ids.add(p.id)

    return render_template(
        'organizer/payment_verification.html',
        user=user,
        payments=payments,
        filter_status=filter_status,
        filter_event_id=filter_event_id,
        my_events=my_events,
        duplicate_payment_ids=duplicate_payment_ids
    )


@organizer_bp.route('/payments/<int:payment_id>/verify', methods=['POST'])
@organizer_bp.route('/payment/<int:payment_id>/verify', methods=['POST'])
@organizer_required
def verify_student_payment(payment_id):
    """
    Organizer approves and verifies student payment proof.
    Transitions Payment to VERIFIED, confirms registration, and generates ticket + QR.
    """
    user = get_current_user()
    payment = Payment.query.get_or_404(payment_id)

    # Security / Authorization: Organizer can ONLY verify payments for their own events
    is_authorized = (payment.organizer_id == user.id) or (payment.event and payment.event.organizer_id == user.id) or user.is_admin
    if not is_authorized:
        abort(403)

    payment.status = PaymentStatus.VERIFIED
    payment.verified_at = datetime.utcnow()
    payment.verified_by_id = user.id
    notes = request.form.get('notes', '').strip()
    payment.verification_reason = notes if notes else f"Payment verified and approved by organizer ({user.name})."

    # Confirm registration and issue ticket
    registration = payment.registration
    if registration:
        registration.status = RegistrationStatus.CONFIRMED
        from services.qr_service import generate_ticket_qr
        if not registration.qr_code_image:
            registration.qr_code_image = generate_ticket_qr(registration.registration_code)

    db.session.commit()

    # Send payment confirmation and ticket email & in-app notification (safely caught)
    try:
        from services.email_service import send_payment_confirmation_email
        target_user = registration.student if (registration and registration.student) else payment.student
        target_event = payment.event or (registration.event if registration else None)
        if target_user and target_event:
            create_notification(
                user_id=target_user.id,
                title=f"Payment Verified: {target_event.title}",
                message=f"Your payment of ₹{payment.amount:.2f} for '{target_event.title}' was verified! Ticket pass #{registration.registration_code if registration else 'active'} is ready.",
                notification_type=NotificationType.SYSTEM,
                link=url_for('student.ticket', code=registration.registration_code) if registration else url_for('student.my_events')
            )
            send_payment_confirmation_email(payment, target_user, target_event, registration)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch payment confirmation notification/email: {exc}")

    flash(f"Payment for {registration.student.name if registration and registration.student else 'student'} has been VERIFIED! Event ticket and QR pass generated.", 'success')
    return redirect(request.referrer or url_for('organizer.dashboard'))


@organizer_bp.route('/payments/<int:payment_id>/reject', methods=['POST'])
@organizer_bp.route('/payment/<int:payment_id>/reject', methods=['POST'])
@organizer_required
def reject_student_payment(payment_id):
    """
    Organizer rejects student payment proof.
    Transitions Payment to REJECTED with a specified reason. No ticket generated.
    """
    user = get_current_user()
    payment = Payment.query.get_or_404(payment_id)

    # Security / Authorization: Organizer can ONLY reject payments for their own events
    is_authorized = (payment.organizer_id == user.id) or (payment.event and payment.event.organizer_id == user.id) or user.is_admin
    if not is_authorized:
        abort(403)

    reason = request.form.get('rejection_reason', '').strip() or 'Payment proof rejected by event organizer.'
    payment.status = PaymentStatus.REJECTED
    payment.verification_reason = reason
    payment.verified_at = datetime.utcnow()
    payment.verified_by_id = user.id

    if payment.registration:
        payment.registration.status = RegistrationStatus.PENDING_PAYMENT

    db.session.commit()

    # Dispatch in-app notification and email to the student
    try:
        from services.email_service import send_payment_rejected_email
        target_user = payment.registration.student if (payment.registration and payment.registration.student) else payment.student
        target_event = payment.event or (payment.registration.event if payment.registration else None)
        if target_user and target_event:
            create_notification(
                user_id=target_user.id,
                title=f"Payment Proof Declined: {target_event.title}",
                message=f"Your payment proof for '{target_event.title}' was rejected by the organizer. Reason: {reason}",
                notification_type=NotificationType.SYSTEM,
                link=url_for('payment.checkout', registration_id=payment.registration_id) if payment.registration_id else url_for('student.my_events')
            )
            send_payment_rejected_email(payment, target_user, target_event, reason=reason)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch payment rejection notification/email: {exc}")

    flash(f"Payment proof has been REJECTED. Reason: {reason}", 'warning')
    return redirect(request.referrer or url_for('organizer.dashboard'))



