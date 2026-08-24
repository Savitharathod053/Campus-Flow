from datetime import datetime
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, abort, send_file
from models import (
    db, Event, EventStatus, EventRegistration, RegistrationStatus,
    CustomRegistrationField, CustomFieldResponse, Payment, PaymentStatus,
    Certificate, CertificateStatus, Announcement, AttendanceRecord
)
from routes.auth import student_required, get_current_user
from services.qr_service import generate_ticket_qr
from services.razorpay_service import create_razorpay_order

student_bp = Blueprint('student', __name__, url_prefix='/student')

@student_bp.route('/dashboard')
@student_required
def dashboard():
    user = get_current_user()
    now = datetime.utcnow()

    # Registrations
    registrations = EventRegistration.query.filter_by(
        student_id=user.id
    ).order_by(EventRegistration.created_at.desc()).all()

    # Confirmed upcoming registered events
    upcoming_registrations = [
        r for r in registrations 
        if r.is_confirmed and r.event.end_time >= now
    ]

    # Completed events
    completed_registrations = [
        r for r in registrations 
        if r.is_confirmed and (r.event.end_time < now or r.event.status == EventStatus.EVENT_COMPLETED)
    ]

    # Certificates count
    certificates = Certificate.query.filter_by(student_id=user.id).all()

    # Recommended events
    recommended_events = Event.query.filter(
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN]),
        Event.end_time >= now
    ).order_by(Event.start_time.asc()).limit(4).all()

    # Registered event announcements
    registered_event_ids = [r.event_id for r in registrations if r.is_confirmed]
    recent_announcements = []
    if registered_event_ids:
        recent_announcements = Announcement.query.filter(
            Announcement.event_id.in_(registered_event_ids)
        ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).limit(5).all()

    return render_template(
        'student/dashboard.html',
        user=user,
        registrations=registrations,
        upcoming_registrations=upcoming_registrations,
        completed_registrations=completed_registrations,
        certificates=certificates,
        recommended_events=recommended_events,
        recent_announcements=recent_announcements
    )


@student_bp.route('/my-events')
@student_required
def my_events():
    user = get_current_user()
    registrations = EventRegistration.query.filter_by(
        student_id=user.id
    ).order_by(EventRegistration.created_at.desc()).all()

    return render_template(
        'student/my_events.html',
        user=user,
        registrations=registrations
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

        # Only generate QR code ticket for free events immediately.
        # For paid events, ticket & QR code will ONLY be generated upon successful payment.
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


@student_bp.route('/ticket/<code>')
@student_required
def ticket(code):
    user = get_current_user()
    registration = EventRegistration.query.filter_by(registration_code=code).first_or_404()

    # Ensure student can only view their own ticket (unless admin/organizer viewing via different route)
    if registration.student_id != user.id and not user.is_admin and not user.is_organizer:
        abort(403)

    # Strictly block ticket access if payment is pending on a paid event
    if not registration.is_confirmed:
        flash('Payment is required before your ticket and QR pass can be generated. Please complete payment.', 'warning')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    # Auto-generate QR code image if confirmed but file not yet generated
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

    # Strict ownership check: prevent unauthorized access
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

    # Strict ownership check: prevent unauthorized access
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
