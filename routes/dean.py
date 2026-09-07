"""
Campus Flow - Students Affairs Dean Portal Blueprint
Implements college-level event review, dual approval finalization,
event publishing, college-wide event monitoring and statistics.
"""
from datetime import datetime
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from sqlalchemy import func, or_
from models import (
    db, User, UserRole, CollegeDepartment, Event, EventStatus, EventType,
    EventRegistration, RegistrationStatus, Payment, PaymentStatus,
    OrganizerRequest, EventRequest, EventRequestStatus, Notification, NotificationType
)
from routes.auth import dean_required, get_current_user
from services.notification_service import create_notification
from services.email_service import (
    send_event_request_dean_approved_email,
    send_event_request_dean_rejected_email
)

dean_bp = Blueprint('dean', __name__, url_prefix='/dean')


@dean_bp.route('/')
@dean_bp.route('/dashboard')
@dean_required
def dashboard():
    user = get_current_user()
    active_tab = request.args.get('tab', 'pending').strip().lower()

    # 1. Event Requests Forwarded after HOD Approval (Strictly pending_dean_approval)
    pending_requests = EventRequest.query.filter_by(
        overall_status=EventRequestStatus.PENDING_DEAN_APPROVAL,
        hod_approval_status='approved'
    ).order_by(EventRequest.hod_decision_at.desc(), EventRequest.created_at.desc()).all()

    # 2. Approved Requests & Published Events
    approved_requests = EventRequest.query.filter_by(
        overall_status=EventRequestStatus.APPROVED
    ).order_by(EventRequest.dean_decision_at.desc()).all()

    # 3. Rejected Event Requests (by Dean or HOD)
    rejected_requests = EventRequest.query.filter(
        EventRequest.overall_status.in_([
            EventRequestStatus.REJECTED_BY_DEAN,
            EventRequestStatus.REJECTED_BY_HOD
        ])
    ).order_by(EventRequest.updated_at.desc()).all()

    # 4. College-wide Event Statistics
    total_approved_events = Event.query.filter_by(is_published=True).count()
    total_registrations = EventRegistration.query.count()
    confirmed_registrations = EventRegistration.query.filter_by(status=RegistrationStatus.CONFIRMED).count()
    total_organizers = User.query.filter_by(role=UserRole.ORGANIZER).count()

    # Department-wise Event Activity
    dept_event_stats = db.session.query(
        CollegeDepartment.code,
        CollegeDepartment.name,
        func.count(Event.id).label('event_count')
    ).outerjoin(Event, (Event.department_id == CollegeDepartment.id) | (Event.department == CollegeDepartment.code))\
     .group_by(CollegeDepartment.code, CollegeDepartment.name).all()

    dept_chart_labels = [row[0] for row in dept_event_stats]
    dept_chart_data = [row[2] for row in dept_event_stats]

    # Department-wise Request Activity Breakdown
    dept_request_counts = {}
    for d in CollegeDepartment.query.filter_by(is_active=True).all():
        total_reqs = EventRequest.query.filter_by(department_id=d.id).count()
        pending_reqs = EventRequest.query.filter_by(department_id=d.id, overall_status=EventRequestStatus.PENDING_DEAN_APPROVAL).count()
        approved_reqs = EventRequest.query.filter_by(department_id=d.id, overall_status=EventRequestStatus.APPROVED).count()
        dept_request_counts[d.code] = {
            'name': d.name,
            'total': total_reqs,
            'pending': pending_reqs,
            'approved': approved_reqs
        }

    return render_template(
        'dean/dashboard.html',
        user=user,
        active_tab=active_tab,
        pending_requests=pending_requests,
        approved_requests=approved_requests,
        rejected_requests=rejected_requests,
        total_approved_events=total_approved_events,
        total_registrations=total_registrations,
        confirmed_registrations=confirmed_registrations,
        total_organizers=total_organizers,
        dept_event_stats=dept_event_stats,
        dept_request_counts=dept_request_counts,
        dept_chart_labels=json.dumps(dept_chart_labels),
        dept_chart_data=json.dumps(dept_chart_data)
    )


@dean_bp.route('/requests/<int:request_id>')
@dean_required
def request_detail(request_id):
    user = get_current_user()
    req = EventRequest.query.get_or_404(request_id)
    return render_template('dean/request_detail.html', user=user, req=req)


@dean_bp.route('/requests/<int:request_id>/approve', methods=['POST'])
@dean_required
def approve_request(request_id):
    user = get_current_user()
    req = EventRequest.query.get_or_404(request_id)

    # STRICT BACKEND DUAL APPROVAL VALIDATION:
    # Dean can ONLY approve if HOD has already approved!
    if req.hod_approval_status != 'approved':
        flash("Unauthorized: This event request cannot be approved by the Dean because it has not received HOD approval.", 'danger')
        return redirect(url_for('dean.dashboard'))

    now = datetime.utcnow()
    req.dean_reviewer_id = user.id
    req.dean_approval_status = 'approved'
    req.dean_decision_at = now
    req.dean_rejection_reason = None
    req.overall_status = EventRequestStatus.APPROVED

    # Create or activate actual Event record using approved request data
    slug = Event.generate_slug(req.event_name)
    dept_obj = req.department
    dept_code = dept_obj.code if dept_obj else 'CSE'

    # Retrieve or create Event
    event = None
    if req.event_id:
        event = db.session.get(Event, req.event_id)

    if not event:
        # Default registration deadline: 1 hour before start_time if not provided
        deadline = req.registration_deadline or req.start_time

        event = Event(
            title=req.event_name,
            slug=slug,
            organizer_id=req.organizer_id,
            event_type=req.category,
            department=dept_code,
            department_id=req.department_id,
            faculty_coordinator=req.faculty_coordinator or (req.hod_reviewer.name if req.hod_reviewer else 'Department Coordinator'),
            faculty_coordinator_contact=req.faculty_coordinator_contact or (req.hod_reviewer.email if req.hod_reviewer else None),
            contact_info=req.contact_info,
            allowed_departments=req.allowed_departments or 'ALL',
            allowed_years=req.allowed_years or 'ALL',
            allowed_sections=req.allowed_sections or 'ALL',
            eligibility_notes=req.eligibility_notes,
            registration_type=req.registration_type or 'INDIVIDUAL',
            min_team_size=req.min_team_size or 2,
            max_team_size=req.max_team_size or 4,
            team_payment_type=req.team_payment_type or 'FREE',
            require_full_team=req.require_full_team or False,
            description=req.description,
            rules=req.rules,
            poster_image=req.poster_image,
            venue=req.venue,
            start_time=req.start_time,
            end_time=req.end_time,
            registration_deadline=deadline,
            max_participants=req.expected_participants,
            registration_fee=req.registration_fee or 0.0,
            is_free=req.is_free,
            upi_id=req.upi_id,
            upi_number=req.upi_number,
            upi_qr_image=req.upi_qr_image,
            payment_instructions=req.payment_instructions,
            enable_attendance=req.enable_attendance,
            min_attendance_percentage=req.min_attendance_percentage or 0.0,
            status=EventStatus.APPROVED,
            event_request_id=req.id
        )
        db.session.add(event)
        db.session.flush()

    # Set dual approval and published flags
    event.is_published = True
    event.hod_approved = True
    event.dean_approved = True
    event.status = EventStatus.APPROVED
    req.event_id = event.id

    db.session.commit()

    # In-App Notifications
    organizer = req.organizer
    hod = req.hod_reviewer or (dept_obj.hod if dept_obj else None)

    create_notification(
        user_id=organizer.id,
        title="Event Approved & Published!",
        message=f"Your event '{req.event_name}' has received final approval from Students Affairs Dean {user.name} and is now published!",
        notification_type=NotificationType.EVENT_DEAN_APPROVED,
        link=url_for('organizer.manage_event', event_id=event.id)
    )

    if hod:
        create_notification(
            user_id=hod.id,
            title="Department Event Published",
            message=f"The event '{req.event_name}' from your department was approved by Dean {user.name} and is now published.",
            notification_type=NotificationType.EVENT_DEAN_APPROVED,
            link=url_for('hod.events')
        )

    # Email Notifications
    try:
        send_event_request_dean_approved_email(req, organizer, hod, user, event)
    except Exception as em_err:
        flash(f"Event published successfully, but notification email dispatch had an issue: {em_err}", 'warning')

    flash(f"Event '{req.event_name}' has received final Dean approval and is now officially published!", 'success')
    return redirect(url_for('dean.dashboard', tab='approved'))


@dean_bp.route('/requests/<int:request_id>/reject', methods=['POST'])
@dean_required
def reject_request(request_id):
    user = get_current_user()
    req = EventRequest.query.get_or_404(request_id)
    reason = request.form.get('reason', '').strip()

    now = datetime.utcnow()
    req.dean_reviewer_id = user.id
    req.dean_approval_status = 'rejected'
    req.dean_decision_at = now
    req.dean_rejection_reason = reason or "Does not meet college-level approval criteria."
    req.overall_status = EventRequestStatus.REJECTED_BY_DEAN

    # Ensure event is NOT published
    if req.event:
        req.event.is_published = False
        req.event.dean_approved = False
        req.event.status = EventStatus.REJECTED
        req.event.rejection_reason = req.dean_rejection_reason

    db.session.commit()

    # In-App Notifications
    organizer = req.organizer
    hod = req.hod_reviewer or (req.department.hod if req.department else None)

    create_notification(
        user_id=organizer.id,
        title="Event Request Declined by Dean",
        message=f"Your event '{req.event_name}' was declined by Students Affairs Dean {user.name}. Reason: {req.dean_rejection_reason}",
        notification_type=NotificationType.EVENT_DEAN_REJECTED,
        link=url_for('organizer.dashboard')
    )

    if hod:
        create_notification(
            user_id=hod.id,
            title="Event Request Declined by Dean",
            message=f"Event proposal '{req.event_name}' was declined by Dean {user.name}. Reason: {req.dean_rejection_reason}",
            notification_type=NotificationType.EVENT_DEAN_REJECTED,
            link=url_for('hod.dashboard')
        )

    # Email Notifications
    try:
        send_event_request_dean_rejected_email(req, organizer, hod, user, reason=req.dean_rejection_reason)
    except Exception as em_err:
        pass

    flash(f"Event request '{req.event_name}' was rejected at the college level.", 'warning')
    return redirect(url_for('dean.dashboard', tab='rejected'))


@dean_bp.route('/events')
@dean_required
def events():
    user = get_current_user()
    search = request.args.get('q', '').strip()
    dept_filter = request.args.get('department', '').strip()

    query = Event.query.filter_by(is_published=True)

    if dept_filter and dept_filter != 'ALL':
        query = query.filter_by(department=dept_filter)

    if search:
        query = query.filter(
            or_(
                Event.title.ilike(f"%{search}%"),
                Event.venue.ilike(f"%{search}%"),
                Event.faculty_coordinator.ilike(f"%{search}%")
            )
        )

    all_events = query.order_by(Event.start_time.desc()).all()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    return render_template(
        'dean/events.html',
        user=user,
        events=all_events,
        departments=departments,
        dept_filter=dept_filter,
        search=search
    )


@dean_bp.route('/organizers')
@dean_required
def organizers():
    user = get_current_user()
    search = request.args.get('q', '').strip()

    query = User.query.filter_by(role=UserRole.ORGANIZER)
    if search:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )
    organizer_list = query.order_by(User.name.asc()).all()

    return render_template(
        'dean/organizers.html',
        user=user,
        organizers=organizer_list,
        search=search
    )
