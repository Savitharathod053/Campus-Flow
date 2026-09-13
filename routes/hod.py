"""
Campus Flow - HOD Portal Blueprint
Department-level organizer request management, event proposal reviews,
department metrics, and student/faculty directories.
Strictly scoped to the HOD's assigned department.
"""
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from sqlalchemy import or_, func
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile,
    Event, EventStatus, EventRegistration, RegistrationStatus,
    AttendanceRecord, Announcement, TargetAudience, CollegeDepartment, Department,
    OrganizerRequest, OrganizerRequestStatus, EventRequest, EventRequestStatus,
    Notification, NotificationType
)
from routes.auth import hod_required, get_current_user
from services.notification_service import create_notification
from services.email_service import (
    send_organizer_request_approved_email,
    send_organizer_request_rejected_email,
    send_event_request_hod_approved_email,
    send_event_request_hod_rejected_email
)

hod_bp = Blueprint('hod', __name__, url_prefix='/hod')


def get_hod_department(user):
    """
    Resolve the specific department managed by this HOD.
    Enforces that an HOD is strictly bound to their assigned department.
    """
    dept = CollegeDepartment.query.filter_by(hod_id=user.id).first()
    if not dept and user.faculty_profile:
        code = user.faculty_profile.department
        dept = CollegeDepartment.query.filter_by(code=code).first()
    return dept


@hod_bp.route('/')
@hod_bp.route('/dashboard')
@hod_required
def dashboard():
    user = get_current_user()
    dept_obj = get_hod_department(user)
    if not dept_obj:
        flash("You are not currently assigned to a department as Head of Department.", 'warning')
        return render_template('hod/no_department.html', user=user)

    dept_id = dept_obj.id
    dept_code = dept_obj.code
    dept_name = dept_obj.name
    active_tab = request.args.get('tab', 'event_pending').strip().lower()

    # 1. ORGANIZER REQUESTS (Strictly Department Scoped)
    pending_organizer_requests = OrganizerRequest.query.filter_by(
        department_id=dept_id,
        status=OrganizerRequestStatus.PENDING
    ).order_by(OrganizerRequest.created_at.desc()).all()

    approved_organizer_requests = OrganizerRequest.query.filter_by(
        department_id=dept_id,
        status=OrganizerRequestStatus.APPROVED
    ).order_by(OrganizerRequest.decision_at.desc()).limit(10).all()

    rejected_organizer_requests = OrganizerRequest.query.filter_by(
        department_id=dept_id,
        status=OrganizerRequestStatus.REJECTED
    ).order_by(OrganizerRequest.decision_at.desc()).limit(10).all()

    # 2. EVENT REQUESTS (Strictly Department Scoped)
    # Section A: Pending Event Approvals (Waiting for this HOD)
    pending_event_requests = EventRequest.query.filter_by(
        department_id=dept_id,
        overall_status=EventRequestStatus.PENDING_HOD_APPROVAL
    ).order_by(EventRequest.created_at.desc()).all()

    # Section B: Approved by Me — Waiting for Dean Approval
    forwarded_event_requests = EventRequest.query.filter_by(
        department_id=dept_id,
        overall_status=EventRequestStatus.PENDING_DEAN_APPROVAL
    ).order_by(EventRequest.hod_decision_at.desc()).all()

    # Section C: Rejected Event Requests
    rejected_event_requests = EventRequest.query.filter_by(
        department_id=dept_id,
        overall_status=EventRequestStatus.REJECTED_BY_HOD
    ).order_by(EventRequest.updated_at.desc()).all()

    # Section D: Department Published Events
    dept_published_events = Event.query.filter(
        (Event.department_id == dept_id) | (Event.department == dept_code),
        Event.is_published == True
    ).order_by(Event.start_time.desc()).limit(8).all()

    # Metrics
    total_students = StudentProfile.query.filter_by(department=dept_code).count()
    total_organizers = OrganizerProfile.query.filter_by(department=dept_code).count()
    total_events_count = Event.query.filter(
        (Event.department_id == dept_id) | (Event.department == dept_code),
        Event.is_published == True
    ).count()

    # Department Announcements
    announcements = Announcement.query.filter(
        Announcement.is_active == True,
        or_(
            Announcement.target_audience == TargetAudience.ALL,
            Announcement.target_audience == 'HOD',
            (Announcement.target_audience == TargetAudience.DEPARTMENT) & (Announcement.target_department == dept_code)
        )
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).limit(5).all()

    return render_template(
        'hod/dashboard.html',
        user=user,
        dept_obj=dept_obj,
        dept_code=dept_code,
        dept_name=dept_name,
        active_tab=active_tab,
        pending_organizer_requests=pending_organizer_requests,
        approved_organizer_requests=approved_organizer_requests,
        rejected_organizer_requests=rejected_organizer_requests,
        pending_event_requests=pending_event_requests,
        forwarded_event_requests=forwarded_event_requests,
        rejected_event_requests=rejected_event_requests,
        dept_published_events=dept_published_events,
        total_students=total_students,
        total_organizers=total_organizers,
        total_events_count=total_events_count,
        announcements=announcements
    )


# ==============================================================================
# ORGANIZER REQUESTS ACTIONS
# ==============================================================================

@hod_bp.route('/organizer-requests/<int:request_id>/approve', methods=['POST'])
@hod_required
def approve_organizer_request(request_id):
    user = get_current_user()
    dept_obj = get_hod_department(user)
    req = OrganizerRequest.query.get_or_404(request_id)

    # Department Access Guard: HOD must not approve requests from another department
    if not dept_obj or req.department_id != dept_obj.id:
        flash("Unauthorized: You can only review organizer requests from your own department.", 'danger')
        return redirect(url_for('hod.dashboard'))

    now = datetime.utcnow()
    req.status = OrganizerRequestStatus.APPROVED
    req.reviewed_by_hod_id = user.id
    req.decision_at = now
    req.rejection_reason = None

    # Promote student to organizer role
    student_user = req.student
    student_user.role = UserRole.ORGANIZER

    # Activate or create OrganizerProfile
    org_profile = student_user.organizer_profile
    if not org_profile:
        org_profile = OrganizerProfile(
            user_id=student_user.id,
            organization_name=f"{student_user.name} - {dept_obj.code} Student Organizer",
            department=dept_obj.code,
            designation="Student Organizer",
            is_verified=True,
            status='APPROVED',
            approved_by_id=user.id,
            approved_at=now
        )
        db.session.add(org_profile)
    else:
        org_profile.is_verified = True
        org_profile.status = 'APPROVED'
        org_profile.approved_by_id = user.id
        org_profile.approved_at = now
        org_profile.department = dept_obj.code

    db.session.commit()

    # In-App Notification to Student
    create_notification(
        user_id=student_user.id,
        title="Organizer Request Approved!",
        message=f"Congratulations! Your Head of Department ({user.name}) has approved your request to become an Event Organizer. You now have access to the Organizer Dashboard.",
        notification_type=NotificationType.ORGANIZER_APPROVAL,
        link=url_for('organizer.dashboard')
    )

    # Email Notification to Student
    try:
        send_organizer_request_approved_email(req, student_user, user)
    except Exception as em_err:
        flash(f"Organizer approved, but email notification had an issue: {em_err}", 'warning')

    flash(f"Student {student_user.name} has been approved as an Organizer.", 'success')
    return redirect(url_for('hod.dashboard', tab='org_approved'))


@hod_bp.route('/organizer-requests/<int:request_id>/reject', methods=['POST'])
@hod_required
def reject_organizer_request(request_id):
    user = get_current_user()
    dept_obj = get_hod_department(user)
    req = OrganizerRequest.query.get_or_404(request_id)

    # Department Access Guard
    if not dept_obj or req.department_id != dept_obj.id:
        flash("Unauthorized: You can only review organizer requests from your own department.", 'danger')
        return redirect(url_for('hod.dashboard'))

    reason = request.form.get('reason', '').strip()
    now = datetime.utcnow()

    req.status = OrganizerRequestStatus.REJECTED
    req.reviewed_by_hod_id = user.id
    req.decision_at = now
    req.rejection_reason = reason or "Does not meet departmental criteria at this time."

    db.session.commit()

    # In-App Notification to Student
    student_user = req.student
    create_notification(
        user_id=student_user.id,
        title="Organizer Request Declined",
        message=f"Your organizer request was declined by HOD {user.name}. Reason: {req.rejection_reason}",
        notification_type=NotificationType.ORGANIZER_REJECTION,
        link=url_for('student.dashboard')
    )

    # Email Notification to Student
    try:
        send_organizer_request_rejected_email(req, student_user, user, reason=req.rejection_reason)
    except Exception as em_err:
        pass

    flash(f"Organizer request from {student_user.name} was rejected.", 'warning')
    return redirect(url_for('hod.dashboard', tab='org_rejected'))


# ==============================================================================
# EVENT REQUESTS ACTIONS (STEP 1 DUAL APPROVAL)
# ==============================================================================

@hod_bp.route('/event-requests/<int:request_id>')
@hod_required
def event_request_detail(request_id):
    user = get_current_user()
    dept_obj = get_hod_department(user)
    req = EventRequest.query.get_or_404(request_id)

    if not dept_obj or req.department_id != dept_obj.id:
        flash("Unauthorized: You can only view event proposals from your own department.", 'danger')
        return redirect(url_for('hod.dashboard'))

    return render_template('hod/event_request_detail.html', user=user, req=req, dept_obj=dept_obj)


@hod_bp.route('/event-requests/<int:request_id>/approve', methods=['POST'])
@hod_required
def approve_event_request(request_id):
    user = get_current_user()
    dept_obj = get_hod_department(user)
    req = EventRequest.query.get_or_404(request_id)

    # Security: HOD must not approve requests from another department
    if not dept_obj or req.department_id != dept_obj.id:
        flash("Unauthorized: You can only approve event proposals belonging to your department.", 'danger')
        return redirect(url_for('hod.dashboard'))

    now = datetime.utcnow()
    req.hod_reviewer_id = user.id
    req.hod_approval_status = 'approved'
    req.hod_decision_at = now
    req.hod_rejection_reason = None
    
    # Step 1 complete -> Forwarded to Dean for Step 2
    req.overall_status = EventRequestStatus.PENDING_DEAN_APPROVAL

    # IMPORTANT: The event must still NOT be published at this stage!
    if req.event:
        req.event.is_published = False
        req.event.hod_approved = True
        req.event.dean_approved = False

    db.session.commit()

    # Identify Students Affairs Dean to notify
    dean = User.query.filter_by(role=UserRole.STUDENTS_AFFAIRS_DEAN, is_active=True).first()

    # In-App Notification to Dean
    if dean:
        create_notification(
            user_id=dean.id,
            title=f"New Event Proposal Forwarded: {req.event_name}",
            message=f"HOD {user.name} ({dept_obj.code}) has approved and forwarded '{req.event_name}' for your final college-level clearance.",
            notification_type=NotificationType.EVENT_HOD_APPROVED,
            link=url_for('dean.request_detail', request_id=req.id)
        )

    # In-App Notification to Organizer
    organizer = req.organizer
    create_notification(
        user_id=organizer.id,
        title="HOD Endorsed Event Proposal",
        message=f"Your event proposal '{req.event_name}' was approved by HOD {user.name} and forwarded to the Students Affairs Dean for final approval.",
        notification_type=NotificationType.EVENT_HOD_APPROVED,
        link=url_for('organizer.dashboard')
    )

    # Email Notifications to Dean and Organizer
    try:
        send_event_request_hod_approved_email(req, organizer, dean, user)
    except Exception as em_err:
        flash(f"Event proposal approved and forwarded, but email notification had an issue: {em_err}", 'warning')

    flash(f"Event proposal '{req.event_name}' endorsed and forwarded to Students Affairs Dean for final approval.", 'success')
    return redirect(url_for('hod.dashboard', tab='event_forwarded'))


@hod_bp.route('/event-requests/<int:request_id>/reject', methods=['POST'])
@hod_required
def reject_event_request(request_id):
    user = get_current_user()
    dept_obj = get_hod_department(user)
    req = EventRequest.query.get_or_404(request_id)

    # Security check
    if not dept_obj or req.department_id != dept_obj.id:
        flash("Unauthorized: You can only reject event proposals belonging to your department.", 'danger')
        return redirect(url_for('hod.dashboard'))

    reason = request.form.get('reason', '').strip()
    now = datetime.utcnow()

    req.hod_reviewer_id = user.id
    req.hod_approval_status = 'rejected'
    req.hod_decision_at = now
    req.hod_rejection_reason = reason or "Does not meet departmental approval criteria."
    req.overall_status = EventRequestStatus.REJECTED_BY_HOD

    # Do not forward to Dean. Do not create or publish event.
    if req.event:
        req.event.is_published = False
        req.event.hod_approved = False
        req.event.status = EventStatus.REJECTED
        req.event.rejection_reason = req.hod_rejection_reason

    db.session.commit()

    # In-App Notification to Organizer
    organizer = req.organizer
    create_notification(
        user_id=organizer.id,
        title="Event Proposal Rejected by HOD",
        message=f"Your event proposal '{req.event_name}' was rejected by HOD {user.name}. Reason: {req.hod_rejection_reason}",
        notification_type=NotificationType.EVENT_HOD_REJECTED,
        link=url_for('organizer.dashboard')
    )

    # Email Notification to Organizer
    try:
        send_event_request_hod_rejected_email(req, organizer, user, reason=req.hod_rejection_reason)
    except Exception as em_err:
        pass

    flash(f"Event proposal '{req.event_name}' was rejected and will not be published.", 'warning')
    return redirect(url_for('hod.dashboard', tab='event_rejected'))


# ==============================================================================
# DEPARTMENT EVENTS, FACULTY & STUDENT DIRECTORIES
# ==============================================================================

@hod_bp.route('/events')
@hod_required
def events():
    user = get_current_user()
    dept_obj = get_hod_department(user)
    if not dept_obj:
        flash("No department assigned to your HOD profile.", 'warning')
        return redirect(url_for('hod.dashboard'))

    dept_id = dept_obj.id
    dept_code = dept_obj.code
    status_filter = request.args.get('status', '').strip()
    search = request.args.get('q', '').strip()

    query = Event.query.filter(
        (Event.department_id == dept_id) | (Event.department == dept_code),
        Event.is_published == True
    )

    if status_filter and status_filter != 'ALL':
        query = query.filter_by(status=status_filter)

    if search:
        query = query.filter(
            or_(
                Event.title.ilike(f"%{search}%"),
                Event.venue.ilike(f"%{search}%"),
                Event.faculty_coordinator.ilike(f"%{search}%")
            )
        )

    dept_events = query.order_by(Event.start_time.desc()).all()

    return render_template(
        'hod/events.html',
        user=user,
        dept_code=dept_code,
        dept_obj=dept_obj,
        events=dept_events,
        status_filter=status_filter,
        search=search,
        event_statuses=EventStatus.CHOICES
    )


@hod_bp.route('/events/<int:event_id>/endorse', methods=['POST'])
@hod_required
def endorse_event(event_id):
    user = get_current_user()
    dept_obj = get_hod_department(user)
    event = Event.query.get_or_404(event_id)

    # Department Access Guard
    if not dept_obj or (event.department_id != dept_obj.id and event.department != dept_obj.code):
        flash("Unauthorized: You can only review events belonging to your department.", 'danger')
        return redirect(url_for('hod.events'))

    action = request.form.get('action', 'approve').strip().lower()

    # If linked to an EventRequest, use standard workflow
    req = EventRequest.query.filter_by(event_id=event.id).first()
    if req:
        if action == 'approve':
            return approve_event_request(req.id)
        else:
            return reject_event_request(req.id)

    # Direct event moderation
    if action == 'approve':
        event.hod_approved = True
        event.status = EventStatus.PENDING_APPROVAL
        db.session.commit()
        flash(f"Event '{event.title}' endorsed. Awaiting Students Affairs Dean final clearance.", 'success')
    else:
        event.hod_approved = False
        event.status = EventStatus.REJECTED
        db.session.commit()
        flash(f"Event '{event.title}' rejected.", 'warning')

    return redirect(url_for('hod.events'))


@hod_bp.route('/faculty')
@hod_required
def faculty():
    user = get_current_user()
    dept_obj = get_hod_department(user)
    dept_code = dept_obj.code if dept_obj else 'CSE'
    search = request.args.get('q', '').strip()

    query = FacultyProfile.query.join(User, FacultyProfile.user_id == User.id)\
        .filter(FacultyProfile.department == dept_code)

    if search:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                FacultyProfile.employee_id.ilike(f"%{search}%"),
                FacultyProfile.designation.ilike(f"%{search}%")
            )
        )

    faculty_members = query.order_by(FacultyProfile.employee_id.asc()).all()

    return render_template(
        'hod/faculty.html',
        user=user,
        dept_code=dept_code,
        dept_obj=dept_obj,
        faculty_members=faculty_members,
        search=search
    )


@hod_bp.route('/students')
@hod_required
def students():
    user = get_current_user()
    dept_obj = get_hod_department(user)
    dept_code = dept_obj.code if dept_obj else 'CSE'
    search = request.args.get('q', '').strip()
    year_filter = request.args.get('year', '').strip()

    query = StudentProfile.query.join(User, StudentProfile.user_id == User.id)\
        .filter(StudentProfile.department == dept_code)

    if year_filter and year_filter != 'ALL':
        try:
            query = query.filter(StudentProfile.year == int(year_filter))
        except ValueError:
            pass

    if search:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                StudentProfile.roll_number.ilike(f"%{search}%"),
                StudentProfile.section.ilike(f"%{search}%")
            )
        )

    students_list = query.order_by(StudentProfile.roll_number.asc()).all()

    return render_template(
        'hod/students.html',
        user=user,
        dept_code=dept_code,
        dept_obj=dept_obj,
        students=students_list,
        search=search,
        year_filter=year_filter
    )


@hod_bp.route('/announcements', methods=['GET', 'POST'])
@hod_required
def announcements():
    user = get_current_user()
    dept_obj = get_hod_department(user)
    dept_code = dept_obj.code if dept_obj else 'CSE'

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        is_pinned = 'is_pinned' in request.form

        if not title or not message:
            flash("Title and message are required for announcements.", 'danger')
        else:
            announcement = Announcement(
                author_id=user.id,
                title=title,
                message=message,
                target_audience=TargetAudience.DEPARTMENT,
                target_department=dept_code,
                is_pinned=is_pinned,
                is_active=True
            )
            db.session.add(announcement)
            db.session.commit()
            flash("Department announcement posted successfully.", 'success')
            return redirect(url_for('hod.announcements'))

    announcements_list = Announcement.query.filter(
        Announcement.target_department == dept_code,
        Announcement.is_active == True
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).all()

    return render_template(
        'hod/announcements.html',
        user=user,
        dept_code=dept_code,
        dept_obj=dept_obj,
        announcements=announcements_list
    )

