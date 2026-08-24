from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from sqlalchemy import func
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile,
    Event, EventStatus, EventRegistration, RegistrationStatus,
    Payment, PaymentStatus, AttendanceRecord, Certificate
)
from routes.auth import admin_required, get_current_user
from services.event_service import delete_expired_events, delete_event_with_cleanup

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    user = get_current_user()

    total_students = User.query.filter_by(role=UserRole.STUDENT).count()
    total_organizers = User.query.filter_by(role=UserRole.ORGANIZER).count()
    total_faculty = User.query.filter_by(role=UserRole.FACULTY_ADMIN).count()

    total_events = Event.query.count()
    pending_events = Event.query.filter_by(status=EventStatus.PENDING_APPROVAL).count()
    pending_organizers = OrganizerProfile.query.filter_by(status='PENDING').count()
    active_events = Event.query.filter(Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN])).count()
    completed_events = Event.query.filter_by(status=EventStatus.EVENT_COMPLETED).count()

    total_registrations = EventRegistration.query.count()
    confirmed_registrations = EventRegistration.query.filter_by(status=RegistrationStatus.CONFIRMED).count()
    total_attendance = AttendanceRecord.query.count()

    # Calculate total revenue
    total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status == PaymentStatus.SUCCESS).scalar() or 0.0

    # Pending lists
    pending_events_list = Event.query.filter_by(status=EventStatus.PENDING_APPROVAL).order_by(Event.created_at.desc()).limit(5).all()
    pending_organizers_list = OrganizerProfile.query.filter_by(status='PENDING').order_by(OrganizerProfile.id.desc()).limit(5).all()

    # Recent registrations
    recent_registrations = EventRegistration.query.order_by(EventRegistration.created_at.desc()).limit(8).all()

    return render_template(
        'admin/dashboard.html',
        user=user,
        total_students=total_students,
        total_organizers=total_organizers,
        total_faculty=total_faculty,
        total_events=total_events,
        pending_events=pending_events,
        pending_organizers=pending_organizers,
        active_events=active_events,
        completed_events=completed_events,
        total_registrations=total_registrations,
        confirmed_registrations=confirmed_registrations,
        total_attendance=total_attendance,
        total_revenue=total_revenue,
        pending_events_list=pending_events_list,
        pending_organizers_list=pending_organizers_list,
        recent_registrations=recent_registrations
    )


@admin_bp.route('/pending-approvals')
@admin_required
def pending_approvals():
    user = get_current_user()
    active_tab = request.args.get('tab', 'events')

    # If the admin belongs to a specific department (and not Dean/General), show department-specific or all
    admin_dept = user.faculty_profile.department if user.faculty_profile else 'General'

    pending_events = Event.query.filter_by(status=EventStatus.PENDING_APPROVAL).order_by(Event.created_at.desc()).all()
    pending_organizers = OrganizerProfile.query.filter_by(status='PENDING').order_by(OrganizerProfile.id.desc()).all()

    return render_template(
        'admin/pending_approvals.html',
        user=user,
        events=pending_events,
        organizers=pending_organizers,
        active_tab=active_tab,
        admin_dept=admin_dept
    )


@admin_bp.route('/events/<int:event_id>/action', methods=['POST'])
@admin_required
def event_action(event_id):
    event = Event.query.get_or_404(event_id)
    action = request.form.get('action') # 'approve', 'reject', 'cancel', 'complete'
    rejection_reason = request.form.get('rejection_reason', '').strip()

    if action == 'approve':
        event.status = EventStatus.APPROVED
        event.rejection_reason = None
        flash(f"Event '{event.title}' approved successfully! Students can now discover and register.", 'success')
    elif action == 'reject':
        event.status = EventStatus.REJECTED
        event.rejection_reason = rejection_reason or "Does not meet college guidelines."
        flash(f"Event '{event.title}' has been rejected.", 'warning')
    elif action == 'cancel':
        event.status = EventStatus.CANCELLED
        flash(f"Event '{event.title}' has been cancelled.", 'danger')
    elif action == 'complete':
        event.status = EventStatus.EVENT_COMPLETED
        flash(f"Event '{event.title}' marked as completed.", 'info')

    db.session.commit()

    redirect_to = request.form.get('redirect_to', 'pending')
    if redirect_to == 'all_events':
        return redirect(url_for('admin.events_list'))
    return redirect(url_for('admin.pending_approvals', tab='events'))


@admin_bp.route('/organizers/<int:organizer_profile_id>/action', methods=['POST'])
@admin_required
def organizer_action(organizer_profile_id):
    current_admin = get_current_user()
    org_profile = OrganizerProfile.query.get_or_404(organizer_profile_id)
    action = request.form.get('action')  # 'approve', 'reject'
    rejection_reason = request.form.get('rejection_reason', '').strip()

    if action == 'approve':
        org_profile.is_verified = True
        org_profile.status = 'APPROVED'
        org_profile.approved_by_id = current_admin.id
        org_profile.approved_at = datetime.utcnow()
        org_profile.rejection_reason = None
        org_profile.user.is_active = True
        flash(f"Organizer '{org_profile.organization_name}' ({org_profile.user.name}) approved! They can now log in and create events.", 'success')
    elif action == 'reject':
        org_profile.is_verified = False
        org_profile.status = 'REJECTED'
        org_profile.rejection_reason = rejection_reason or "Registration does not meet department approval criteria."
        flash(f"Organizer application for '{org_profile.organization_name}' rejected.", 'warning')

    db.session.commit()
    return redirect(url_for('admin.pending_approvals', tab='organizers'))


@admin_bp.route('/events')
@admin_required
def events_list():
    user = get_current_user()
    status_filter = request.args.get('status', '').strip()
    search = request.args.get('q', '').strip()

    query = Event.query

    if status_filter and status_filter != 'ALL':
        query = query.filter_by(status=status_filter)

    if search:
        query = query.filter((Event.title.ilike(f'%{search}%')) | (Event.department.ilike(f'%{search}%')))

    events = query.order_by(Event.created_at.desc()).all()
    return render_template('admin/events_list.html', user=user, events=events, status_filter=status_filter, search=search, event_statuses=EventStatus.CHOICES)


@admin_bp.route('/events/delete-expired', methods=['POST'])
@admin_required
def delete_expired():
    count, deleted_titles, skipped_titles = delete_expired_events(require_certificates_done=True)
    if count > 0:
        flash(f"Successfully deleted {count} expired event(s) where all certificates have been issued to students.", 'success')
    elif skipped_titles:
        flash(f"No events deleted: {len(skipped_titles)} expired event(s) were retained because certificate submission to students is not yet over.", 'warning')
    else:
        flash("No expired events found.", 'info')

    if skipped_titles and count > 0:
        flash(f"{len(skipped_titles)} expired event(s) were retained because certificate submission to students is still pending.", 'info')

    return redirect(url_for('admin.events_list'))


@admin_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@admin_required
def delete_event(event_id):
    from services.event_service import are_certificates_completed
    event = Event.query.get_or_404(event_id)
    
    if not are_certificates_completed(event):
        flash(f"Cannot delete event '{event.title}': Certificate submission to attending students is not yet completed. Please issue all certificates before deleting.", 'danger')
        return redirect(url_for('admin.events_list'))

    title = event.title
    delete_event_with_cleanup(event)
    db.session.commit()
    flash(f"Event '{title}' and all associated records were permanently deleted.", 'success')
    return redirect(url_for('admin.events_list'))


@admin_bp.route('/users')
@admin_required
def users_list():
    user = get_current_user()
    role_filter = request.args.get('role', '').strip()
    search = request.args.get('q', '').strip()

    query = User.query

    if role_filter and role_filter != 'ALL':
        query = query.filter_by(role=role_filter)

    if search:
        query = query.filter(
            (User.name.ilike(f'%{search}%')) | 
            (User.email.ilike(f'%{search}%')) |
            (User.phone.ilike(f'%{search}%'))
        )

    users = query.order_by(User.created_at.desc()).all()
    return render_template('admin/users_list.html', user=user, users=users, role_filter=role_filter, search=search, user_roles=UserRole.CHOICES)


@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@admin_required
def toggle_user_status(user_id):
    current_admin = get_current_user()
    target_user = User.query.get_or_404(user_id)

    if target_user.id == current_admin.id:
        flash('You cannot deactivate your own administrative account.', 'danger')
        return redirect(url_for('admin.users_list'))

    target_user.is_active = not target_user.is_active
    db.session.commit()

    status_str = 'activated' if target_user.is_active else 'deactivated'
    flash(f"User '{target_user.name}' ({target_user.email}) has been {status_str}.", 'info')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/reports')
@admin_required
def reports():
    user = get_current_user()

    # 1. Department-wise registration breakdown
    dept_stats = db.session.query(
        StudentProfile.department,
        func.count(EventRegistration.id).label('reg_count')
    ).join(User, StudentProfile.user_id == User.id)\
     .join(EventRegistration, EventRegistration.student_id == User.id)\
     .filter(EventRegistration.status == RegistrationStatus.CONFIRMED)\
     .group_by(StudentProfile.department).all()

    # 2. Year-wise breakdown
    year_stats = db.session.query(
        StudentProfile.year,
        func.count(EventRegistration.id).label('reg_count')
    ).join(User, StudentProfile.user_id == User.id)\
     .join(EventRegistration, EventRegistration.student_id == User.id)\
     .filter(EventRegistration.status == RegistrationStatus.CONFIRMED)\
     .group_by(StudentProfile.year).all()

    # 3. Event-wise participation and revenue
    events = Event.query.order_by(Event.created_at.desc()).all()
    event_metrics = []
    for e in events:
        total_reg = e.registrations.count()
        confirmed_reg = e.registrations.filter_by(status=RegistrationStatus.CONFIRMED).count()
        attended_reg = len(e.attendance_records)
        revenue = sum([r.payment.amount for r in e.registrations if r.payment and r.payment.status == PaymentStatus.SUCCESS])
        attendance_pct = (attended_reg / confirmed_reg * 100) if confirmed_reg > 0 else 0

        event_metrics.append({
            'event': e,
            'total_reg': total_reg,
            'confirmed_reg': confirmed_reg,
            'attended_reg': attended_reg,
            'attendance_pct': round(attendance_pct, 1),
            'revenue': revenue
        })

    # Overall totals
    total_confirmed = EventRegistration.query.filter_by(status=RegistrationStatus.CONFIRMED).count()
    total_attended = AttendanceRecord.query.count()
    total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status == PaymentStatus.SUCCESS).scalar() or 0.0

    return render_template(
        'admin/reports.html',
        user=user,
        dept_stats=dept_stats,
        year_stats=year_stats,
        event_metrics=event_metrics,
        total_confirmed=total_confirmed,
        total_attended=total_attended,
        total_revenue=total_revenue
    )
