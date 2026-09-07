from datetime import datetime, timedelta
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, abort, send_file
from models import (
    db, Event, EventStatus, EventRegistration, RegistrationStatus,
    CustomRegistrationField, CustomFieldResponse, Payment, PaymentStatus,
    Certificate, CertificateStatus, Announcement, AttendanceRecord,
    Team, TeamStatus, TeamPaymentStatus, TeamRole, TeamMemberStatus,
    InvitationStatus, TeamMember, TeamInvitation, EventRegistrationType, TeamPaymentType,
    CollegeDepartment, OrganizerRequest, OrganizerRequestStatus, NotificationType
)
from routes.auth import student_required, login_required, get_current_user
from services.qr_service import generate_ticket_qr
from services.notification_service import create_notification
from services.email_service import send_organizer_request_submitted_email
from services.team_service import (
    create_team, accept_invitation as service_accept_invitation,
    decline_invitation as service_decline_invitation,
    invite_member as service_invite_member,
    resend_invitation as service_resend_invitation,
    remove_or_cancel_member,
    process_team_payment_success,
    TeamValidationError
)
from services.event_service import delete_expired_event_announcements

student_bp = Blueprint('student', __name__, url_prefix='/student')

@student_bp.route('/dashboard')
@student_required
def dashboard():
    user = get_current_user()
    now = datetime.utcnow()

    # Purge any announcements belonging to expired events or stale broadcasts (>24h) from database
    delete_expired_event_announcements(now, max_age_hours=24)

    # Registrations
    registrations = EventRegistration.query.filter_by(
        student_id=user.id
    ).order_by(EventRegistration.created_at.desc()).all()

    # Confirmed active upcoming registered events (exclude completed, expired and cancelled)
    upcoming_registrations = [
        r for r in registrations 
        if r.is_confirmed and not r.event.is_completed and not r.event.is_expired and r.event.status != EventStatus.CANCELLED
    ]

    # Completed events (either ended by time or marked completed)
    completed_registrations = [
        r for r in registrations 
        if r.is_confirmed and (r.event.is_completed or r.event.is_expired)
    ]

    # Certificates count
    certificates = Certificate.query.filter_by(student_id=user.id).all()

    # Recommended events (only active, dual-approved, published, upcoming, non-expired events)
    registered_event_ids = {r.event_id for r in registrations}
    recommended_candidates = Event.query.filter(
        Event.is_published == True,
        Event.hod_approved == True,
        Event.dean_approved == True,
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN, EventStatus.UPCOMING]),
        Event.start_time > now,
        Event.end_time > now,
        Event.registration_deadline > now,
        Event.status.notin_([EventStatus.COMPLETED, 'EVENT_COMPLETED', EventStatus.CANCELLED, EventStatus.REJECTED])
    ).order_by(Event.start_time.asc()).limit(12).all()
    recommended_events = [
        e for e in recommended_candidates 
        if not e.is_completed and not e.is_expired and not e.is_deadline_passed and e.is_upcoming and e.id not in registered_event_ids
    ][:4]

    # Registered event announcements (ONLY for active non-completed, non-expired events within 24 hours)
    active_registered_event_ids = [
        r.event_id for r in upcoming_registrations 
        if r.event and not r.event.is_expired and not r.event.is_completed
    ]
    recent_announcements = []
    if active_registered_event_ids:
        raw_announcements = Announcement.query.filter(
            Announcement.event_id.in_(active_registered_event_ids),
            Announcement.is_active == True,
            Announcement.created_at >= now - timedelta(hours=24)
        ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).limit(10).all()

        deleted_stale = False
        for a in raw_announcements:
            is_expired_event = a.event and (a.event.is_expired or a.event.is_completed)
            is_stale_time = a.created_at and (now - a.created_at) > timedelta(hours=24)
            if is_expired_event or is_stale_time:
                db.session.delete(a)
                deleted_stale = True
            elif a.event and not a.event.is_expired and not a.event.is_completed:
                recent_announcements.append(a)

        if deleted_stale:
            db.session.commit()

        recent_announcements = recent_announcements[:5]

    # Teams where user is Lead or Member
    team_memberships = TeamMember.query.filter_by(student_id=user.id).all()
    my_team_ids = [tm.team_id for tm in team_memberships]
    my_teams = Team.query.filter(Team.id.in_(my_team_ids)).order_by(Team.created_at.desc()).all() if my_team_ids else []

    # Active pending invitations for current student's email
    pending_invitations = TeamInvitation.query.filter(
        TeamInvitation.invited_email == user.email.lower(),
        TeamInvitation.status == InvitationStatus.PENDING,
        TeamInvitation.expires_at >= now
    ).order_by(TeamInvitation.created_at.desc()).all()

    # My Organizer Requests (Track status, HOD decision, date, rejection reason)
    my_organizer_requests = OrganizerRequest.query.filter_by(
        student_id=user.id
    ).order_by(OrganizerRequest.created_at.desc()).all()

    has_pending_organizer_request = any(r.status == OrganizerRequestStatus.PENDING for r in my_organizer_requests)

    return render_template(
        'student/dashboard.html',
        user=user,
        registrations=registrations,
        upcoming_registrations=upcoming_registrations,
        completed_registrations=completed_registrations,
        certificates=certificates,
        recommended_events=recommended_events,
        recent_announcements=recent_announcements,
        my_teams=my_teams,
        pending_invitations=pending_invitations,
        my_organizer_requests=my_organizer_requests,
        has_pending_organizer_request=has_pending_organizer_request
    )


@student_bp.route('/organizer-request', methods=['GET', 'POST'])
@student_required
def request_organizer():
    user = get_current_user()
    student_profile = user.student_profile

    if not student_profile:
        flash('Student profile not found. Please complete your student profile before applying.', 'danger')
        return redirect(url_for('student.dashboard'))

    # Department is strictly locked to the student's department
    dept_code = student_profile.department
    dept_obj = CollegeDepartment.query.filter_by(code=dept_code).first()
    if not dept_obj:
        flash(f"Department '{dept_code}' is not currently configured in the department directory.", 'danger')
        return redirect(url_for('student.dashboard'))

    # Check if student already has a pending request
    pending_req = OrganizerRequest.query.filter_by(
        student_id=user.id,
        status=OrganizerRequestStatus.PENDING
    ).first()

    if pending_req:
        flash('You already have an organizer request pending review by your Department HOD.', 'warning')
        return redirect(url_for('student.dashboard'))

    if request.method == 'POST':
        reason = request.form.get('reason', '').strip()
        previous_experience = request.form.get('previous_experience', '').strip()

        if not reason:
            flash('Please state why you want to become an organizer.', 'danger')
            return redirect(url_for('student.dashboard'))

        # Create Organizer Request strictly routed to student's department
        org_req = OrganizerRequest(
            student_id=user.id,
            department_id=dept_obj.id,
            reason=reason,
            previous_experience=previous_experience,
            status=OrganizerRequestStatus.PENDING
        )
        db.session.add(org_req)
        db.session.commit()

        # Step 1: Identify HOD assigned to that department
        hod_user = dept_obj.hod
        if hod_user:
            # Create In-App Notification for HOD
            create_notification(
                user_id=hod_user.id,
                title=f"New Organizer Request: {user.name}",
                message=f"Student {user.name} (Roll: {student_profile.roll_number}) from {dept_obj.code} has submitted a request to become an Event Organizer.",
                notification_type=NotificationType.ORGANIZER_REQUEST,
                link=url_for('hod.dashboard', tab='org_pending')
            )
            # Send Email Notification to HOD
            try:
                send_organizer_request_submitted_email(org_req, user, hod_user, dept_obj)
            except Exception as em_err:
                pass

        flash('Your request to become an Organizer has been submitted to your Department HOD for review!', 'success')
        return redirect(url_for('student.dashboard'))

    return redirect(url_for('student.dashboard'))


@student_bp.route('/my-events')
@student_required
def my_events():
    user = get_current_user()
    tab = request.args.get('tab', 'active').strip().lower()

    registrations = EventRegistration.query.filter_by(
        student_id=user.id
    ).order_by(EventRegistration.created_at.desc()).all()

    active_registrations = [r for r in registrations if not r.event.is_completed and r.event.status != EventStatus.CANCELLED]
    completed_registrations = [r for r in registrations if r.event.is_completed or r.event.status == EventStatus.CANCELLED]

    if tab in ('completed', 'history'):
        displayed_registrations = completed_registrations
    elif tab == 'all':
        displayed_registrations = registrations
    else:
        tab = 'active'
        displayed_registrations = active_registrations

    return render_template(
        'student/my_events.html',
        user=user,
        registrations=displayed_registrations,
        active_registrations_count=len(active_registrations),
        completed_registrations_count=len(completed_registrations),
        total_registrations_count=len(registrations),
        current_tab=tab
    )


@student_bp.route('/my-teams')
@student_required
def my_teams():
    user = get_current_user()
    now = datetime.utcnow()

    # Teams where user is member or lead
    memberships = TeamMember.query.filter_by(student_id=user.id).all()
    team_ids = [m.team_id for m in memberships]
    teams = Team.query.filter(Team.id.in_(team_ids)).order_by(Team.created_at.desc()).all() if team_ids else []

    # Pending Invitations
    invitations = TeamInvitation.query.filter(
        TeamInvitation.invited_email == user.email.lower(),
        TeamInvitation.status == InvitationStatus.PENDING,
        TeamInvitation.expires_at >= now
    ).order_by(TeamInvitation.created_at.desc()).all()

    return render_template(
        'student/my_teams.html',
        user=user,
        teams=teams,
        invitations=invitations
    )


@student_bp.route('/teams/<int:team_id>')
@student_required
def team_detail(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)

    # Authorization: Student must be lead, member, or an admin/organizer
    is_member = any(m.student_id == user.id for m in team.members)
    is_lead = team.team_lead_id == user.id

    if not is_member and not is_lead and not user.is_admin and not user.is_organizer:
        abort(403)

    event = team.event
    return render_template(
        'student/team_detail.html',
        user=user,
        team=team,
        event=event,
        is_lead=is_lead
    )


@student_bp.route('/register/<int:event_id>', methods=['GET', 'POST'])
@student_required
def register_event(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    # 1. Check if already registered
    existing_reg = EventRegistration.query.filter_by(
        event_id=event.id,
        student_id=user.id
    ).first()

    if existing_reg:
        if existing_reg.is_confirmed:
            flash('You are already registered for this event.', 'info')
            return redirect(url_for('student.ticket', code=existing_reg.registration_code))
        elif existing_reg.status == RegistrationStatus.PENDING_PAYMENT:
            # Resume payment
            return redirect(url_for('payment.checkout', registration_id=existing_reg.id))

    # 2. Check Event status and capacity
    if not event.is_live_registration_open:
        flash('Registration for this event is currently closed or unavailable.', 'danger')
        return redirect(url_for('public.event_detail', slug=event.slug))

    # 3. Check Eligibility
    is_eligible, reason = event.check_student_eligibility(user.student_profile)
    if not is_eligible:
        flash(f'Eligibility check failed: {reason}', 'danger')
        return redirect(url_for('public.event_detail', slug=event.slug))

    custom_fields = event.custom_fields

    if request.method == 'POST':
        # Validate custom fields
        custom_responses_data = {}
        missing_required = []

        for field in custom_fields:
            form_key = f"custom_field_{field.id}"
            value = request.form.get(form_key, '').strip()
            if field.is_required and not value:
                missing_required.append(field.field_label)
            custom_responses_data[field.id] = value

        if missing_required:
            flash(f"Please fill all required fields: {', '.join(missing_required)}", 'danger')
            return render_template('student/register_event.html', event=event, user=user, custom_fields=custom_fields)

        # Create registration
        reg_code = EventRegistration.generate_registration_code(event.id, user.id)
        
        # Free vs Paid logic
        is_free_event = event.is_free or event.registration_fee <= 0
        init_status = RegistrationStatus.CONFIRMED if is_free_event else RegistrationStatus.PENDING_PAYMENT

        qr_path = generate_ticket_qr(reg_code) if is_free_event else None

        registration = EventRegistration(
            event_id=event.id,
            student_id=user.id,
            registration_code=reg_code,
            qr_code_image=qr_path,
            status=init_status
        )
        db.session.add(registration)
        db.session.flush()

        # Save custom field answers
        for field_id, resp_value in custom_responses_data.items():
            if resp_value:
                response_obj = CustomFieldResponse(
                    registration_id=registration.id,
                    field_id=field_id,
                    field_value=resp_value
                )
                db.session.add(response_obj)

        db.session.commit()

        if is_free_event:
            # Send ticket and registration confirmation email
            try:
                from services.email_service import send_registration_confirmation_email
                send_registration_confirmation_email(registration, user, event)
            except Exception as exc:
                current_app.logger.warning(f"Could not dispatch registration confirmation email: {exc}")

            flash('Registration successful! Your digital ticket and QR code are ready.', 'success')
            return redirect(url_for('student.ticket', code=registration.registration_code))
        else:
            flash('Registration submitted! Please complete the fee payment to generate and receive your ticket.', 'info')
            return redirect(url_for('payment.checkout', registration_id=registration.id))

    return render_template(
        'student/register_event.html',
        event=event,
        user=user,
        custom_fields=custom_fields
    )


@student_bp.route('/register-team/<int:event_id>', methods=['GET', 'POST'])
@student_required
def register_team(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    if not event.allows_team_registration:
        flash('This event does not allow team registrations.', 'danger')
        return redirect(url_for('public.event_detail', slug=event.slug))

    if not event.is_live_registration_open:
        flash('Registration for this event is currently closed or full.', 'danger')
        return redirect(url_for('public.event_detail', slug=event.slug))

    # Check if already registered or in team
    existing_reg = EventRegistration.query.filter_by(event_id=event.id, student_id=user.id).first()
    if existing_reg:
        if existing_reg.team_id:
            flash('You are already registered in a team for this event.', 'info')
            return redirect(url_for('student.team_detail', team_id=existing_reg.team_id))
        else:
            flash('You are already registered individually for this event.', 'info')
            return redirect(url_for('student.ticket', code=existing_reg.registration_code))

    custom_fields = event.custom_fields

    if request.method == 'POST':
        team_name = request.form.get('team_name', '').strip()
        member_emails = request.form.getlist('member_emails[]')
        # Also handle comma-separated or multiple inputs
        if not member_emails:
            raw_emails = request.form.get('member_emails_text', '')
            if raw_emails:
                member_emails = [e.strip() for e in raw_emails.replace(',', '\n').split('\n') if e.strip()]

        # Filter empty
        member_emails = [e.strip() for e in member_emails if e.strip()]

        # Validate custom fields
        custom_responses_data = {}
        missing_required = []
        for field in custom_fields:
            form_key = f"custom_field_{field.id}"
            value = request.form.get(form_key, '').strip()
            if field.is_required and not value:
                missing_required.append(field.field_label)
            custom_responses_data[field.id] = value

        if missing_required:
            flash(f"Please fill all required questions: {', '.join(missing_required)}", 'danger')
            return render_template('student/register_team.html', event=event, user=user, custom_fields=custom_fields)

        try:
            team, lead_reg = create_team(
                event=event,
                lead_user=user,
                team_name=team_name,
                member_emails=member_emails,
                custom_responses_data=custom_responses_data
            )
            flash(f"Team '{team.team_name}' registered successfully! Invitations have been dispatched to your team members.", 'success')
            
            # If Per-Team payment is required, redirect to checkout
            if event.team_payment_type == TeamPaymentType.PER_TEAM and not event.is_free and event.registration_fee > 0:
                return redirect(url_for('student.team_checkout', team_id=team.id))
            elif event.team_payment_type == TeamPaymentType.PER_PERSON and not event.is_free and event.registration_fee > 0:
                return redirect(url_for('payment.checkout', registration_id=lead_reg.id))
            else:
                return redirect(url_for('student.team_detail', team_id=team.id))

        except TeamValidationError as e:
            flash(str(e), 'danger')
            return render_template('student/register_team.html', event=event, user=user, custom_fields=custom_fields)

    return render_template(
        'student/register_team.html',
        event=event,
        user=user,
        custom_fields=custom_fields
    )


@student_bp.route('/team-invitations')
@student_required
def team_invitations():
    return redirect(url_for('student.my_teams'))


@student_bp.route('/team-invitations/<token>/accept', methods=['GET', 'POST'])
def accept_invitation(token):
    invitation = TeamInvitation.query.filter_by(token=token).first_or_404()
    user = get_current_user()

    # If not logged in, prompt login or registration with next URL
    if not user:
        flash(f"Please log in or register with email '{invitation.invited_email}' to accept this team invitation.", 'info')
        return redirect(url_for('auth.login', next=request.url))

    if not user.is_student:
        flash('Only students can participate in teams.', 'danger')
        return redirect(url_for('public.home'))

    try:
        team, registration = service_accept_invitation(token, user)
        flash(f"Success! You have joined team '{team.team_name}' for '{team.event.title}'.", 'success')
        
        if registration.is_confirmed:
            return redirect(url_for('student.ticket', code=registration.registration_code))
        else:
            flash('Your membership is accepted! Please complete individual registration payment to generate your ticket.', 'info')
            return redirect(url_for('payment.checkout', registration_id=registration.id))

    except TeamValidationError as e:
        flash(str(e), 'danger')
        return redirect(url_for('student.my_teams'))


@student_bp.route('/team-invitations/<token>/decline', methods=['GET', 'POST'])
def decline_invitation(token):
    invitation = TeamInvitation.query.filter_by(token=token).first_or_404()
    user = get_current_user()

    try:
        service_decline_invitation(token, user)
        flash("You have declined the team invitation.", 'info')
    except TeamValidationError as e:
        flash(str(e), 'danger')

    if user:
        return redirect(url_for('student.my_teams'))
    return redirect(url_for('public.home'))


@student_bp.route('/teams/<int:team_id>/invite', methods=['POST'])
@student_required
def invite_team_member(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)

    email = request.form.get('email', '').strip()
    try:
        service_invite_member(team, email, user)
        flash(f"Invitation sent successfully to {email}!", 'success')
    except TeamValidationError as e:
        flash(str(e), 'danger')

    return redirect(url_for('student.team_detail', team_id=team.id))


@student_bp.route('/teams/<int:team_id>/resend/<int:invitation_id>', methods=['POST'])
@student_required
def resend_team_invitation(team_id, invitation_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)

    try:
        service_resend_invitation(team, invitation_id, user)
        flash("Invitation resent successfully!", 'success')
    except TeamValidationError as e:
        flash(str(e), 'danger')

    return redirect(url_for('student.team_detail', team_id=team.id))


@student_bp.route('/teams/<int:team_id>/remove-member/<int:member_id>', methods=['POST'])
@student_required
def remove_team_member(team_id, member_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)

    try:
        remove_or_cancel_member(team, member_id, user, is_invite=False)
        flash("Team member removed successfully.", 'info')
    except TeamValidationError as e:
        flash(str(e), 'danger')

    return redirect(url_for('student.team_detail', team_id=team.id))


@student_bp.route('/teams/<int:team_id>/cancel-invite/<int:invitation_id>', methods=['POST'])
@student_required
def cancel_team_invitation(team_id, invitation_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)

    try:
        remove_or_cancel_member(team, invitation_id, user, is_invite=True)
        flash("Invitation cancelled.", 'info')
    except TeamValidationError as e:
        flash(str(e), 'danger')

    return redirect(url_for('student.team_detail', team_id=team.id))


@student_bp.route('/teams/<int:team_id>/checkout')
@student_required
def team_checkout(team_id):
    user = get_current_user()
    team = Team.query.get_or_404(team_id)

    if team.team_lead_id != user.id and not user.is_admin:
        flash("Only the team lead can make the team fee payment.", 'warning')
        return redirect(url_for('student.team_detail', team_id=team.id))

    if team.payment_status == TeamPaymentStatus.PAID:
        flash("Team payment has already been completed.", 'info')
        return redirect(url_for('student.team_detail', team_id=team.id))

    lead_reg = EventRegistration.query.filter_by(team_id=team.id, student_id=user.id).first()
    if lead_reg:
        return redirect(url_for('payment.checkout', registration_id=lead_reg.id))

    flash("Team registration record not found for payment.", 'danger')
    return redirect(url_for('student.team_detail', team_id=team.id))


@student_bp.route('/ticket/<code>')
@student_required
def ticket(code):
    user = get_current_user()
    registration = EventRegistration.query.filter_by(registration_code=code).first_or_404()

    if registration.student_id != user.id and not user.is_admin and not user.is_organizer:
        abort(403)

    if not registration.is_confirmed:
        flash('Payment is required before your ticket and QR pass can be generated. Please complete payment.', 'warning')
        if registration.team and registration.team.event.team_payment_type == TeamPaymentType.PER_TEAM:
            return redirect(url_for('student.team_checkout', team_id=registration.team_id))
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    if not registration.qr_code_image:
        registration.qr_code_image = generate_ticket_qr(registration.registration_code)
        db.session.commit()

    return render_template('student/ticket.html', registration=registration, user=user)


@student_bp.route('/certificates')
@student_required
def certificates():
    user = get_current_user()
    certs = Certificate.query.filter(
        Certificate.student_id == user.id,
        Certificate.status.in_([CertificateStatus.MATCHED, CertificateStatus.MANUALLY_ASSIGNED])
    ).order_by(Certificate.created_at.desc()).all()
    return render_template('student/certificates.html', user=user, certificates=certs)


@student_bp.route('/certificates/<int:cert_id>/download')
@student_required
def download_certificate(cert_id):
    user = get_current_user()
    cert = Certificate.query.get_or_404(cert_id)

    if cert.student_id != user.id and not user.is_admin:
        abort(403)

    if cert.status not in (CertificateStatus.MATCHED, CertificateStatus.MANUALLY_ASSIGNED):
        abort(404)

    full_path = Path(__file__).resolve().parent.parent / 'static' / cert.file_path
    if not full_path.exists():
        abort(404)

    return send_file(
        str(full_path),
        as_attachment=True,
        download_name=cert.original_filename
    )


@student_bp.route('/certificates/<int:cert_id>/preview')
@student_required
def preview_certificate(cert_id):
    user = get_current_user()
    cert = Certificate.query.get_or_404(cert_id)

    if cert.student_id != user.id and not user.is_admin:
        abort(403)

    if cert.status not in (CertificateStatus.MATCHED, CertificateStatus.MANUALLY_ASSIGNED):
        abort(404)

    full_path = Path(__file__).resolve().parent.parent / 'static' / cert.file_path
    if not full_path.exists():
        abort(404)

    mimetype = 'application/pdf' if cert.is_pdf else 'image/png'
    return send_file(
        str(full_path),
        mimetype=mimetype,
        as_attachment=False
    )
