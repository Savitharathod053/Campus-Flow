"""
Campus Flow - Faculty Portal Blueprint
Provides department event tracking, student rosters, coordinated events,
and departmental announcements for faculty members.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from sqlalchemy import or_
from models import (
    db, User, UserRole, StudentProfile, FacultyProfile,
    Event, EventStatus, EventRegistration, RegistrationStatus,
    AttendanceRecord, Announcement, TargetAudience, CollegeDepartment
)
from routes.auth import faculty_required, get_current_user

faculty_bp = Blueprint('faculty', __name__, url_prefix='/faculty')


@faculty_bp.route('/')
@faculty_bp.route('/dashboard')
def dashboard():
    user = get_current_user()
    if user and user.is_hod:
        return redirect(url_for('hod.dashboard'))
    return redirect(url_for('auth.login'))

    # Department and Coordinated Events
    dept_events_query = Event.query.filter(
        or_(
            Event.department == dept,
            Event.faculty_coordinator.ilike(f"%{user.name}%")
        )
    )
    total_dept_events = dept_events_query.count()
    active_dept_events = dept_events_query.filter(
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN])
    ).count()

    # Department Students
    dept_students_count = StudentProfile.query.filter_by(department=dept).count()

    # Upcoming / Recent Department Events
    recent_events = dept_events_query.order_by(Event.start_time.desc()).limit(6).all()

    # Coordinated Events by this faculty member
    coordinated_events = Event.query.filter(
        Event.faculty_coordinator.ilike(f"%{user.name}%")
    ).order_by(Event.start_time.desc()).all()

    # Relevant Announcements
    announcements = Announcement.query.filter(
        Announcement.is_active == True,
        or_(
            Announcement.target_audience == TargetAudience.ALL,
            Announcement.target_audience == 'FACULTY',
            (Announcement.target_audience == TargetAudience.DEPARTMENT) & (Announcement.target_department == dept)
        )
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).limit(5).all()

    return render_template(
        'faculty/dashboard.html',
        user=user,
        dept=dept,
        total_dept_events=total_dept_events,
        active_dept_events=active_dept_events,
        dept_students_count=dept_students_count,
        recent_events=recent_events,
        coordinated_events=coordinated_events,
        announcements=announcements
    )


@faculty_bp.route('/events')
@faculty_required
def events():
    user = get_current_user()
    dept = user.faculty_profile.department if user.faculty_profile else 'General'
    status_filter = request.args.get('status', '').strip()
    search = request.args.get('q', '').strip()

    query = Event.query.filter(
        or_(
            Event.department == dept,
            Event.faculty_coordinator.ilike(f"%{user.name}%")
        )
    )

    if status_filter and status_filter != 'ALL':
        query = query.filter(Event.status == status_filter)

    if search:
        query = query.filter(
            or_(
                Event.title.ilike(f"%{search}%"),
                Event.venue.ilike(f"%{search}%")
            )
        )

    dept_events = query.order_by(Event.start_time.desc()).all()

    return render_template(
        'faculty/events.html',
        user=user,
        dept=dept,
        events=dept_events,
        status_filter=status_filter,
        search=search,
        event_statuses=EventStatus.CHOICES
    )


@faculty_bp.route('/students')
@faculty_required
def students():
    user = get_current_user()
    dept = user.faculty_profile.department if user.faculty_profile else 'General'
    search = request.args.get('q', '').strip()
    year_filter = request.args.get('year', '').strip()

    query = StudentProfile.query.join(User, StudentProfile.user_id == User.id)\
        .filter(StudentProfile.department == dept)

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

    dept_students = query.order_by(StudentProfile.year.asc(), StudentProfile.roll_number.asc()).all()

    return render_template(
        'faculty/students.html',
        user=user,
        dept=dept,
        students=dept_students,
        search=search,
        year_filter=year_filter
    )


@faculty_bp.route('/attendance')
@faculty_required
def attendance():
    user = get_current_user()
    dept = user.faculty_profile.department if user.faculty_profile else 'General'
    event_id = request.args.get('event_id', type=int)

    events_list = Event.query.filter(
        or_(
            Event.department == dept,
            Event.faculty_coordinator.ilike(f"%{user.name}%")
        )
    ).order_by(Event.start_time.desc()).all()

    selected_event = None
    records = []
    if event_id:
        selected_event = Event.query.get(event_id)
        if selected_event and (selected_event.department == dept or user.name.lower() in (selected_event.faculty_coordinator or '').lower()):
            records = AttendanceRecord.query.filter_by(event_id=selected_event.id)\
                .order_by(AttendanceRecord.scanned_at.desc()).all()
    elif events_list:
        selected_event = events_list[0]
        records = AttendanceRecord.query.filter_by(event_id=selected_event.id)\
            .order_by(AttendanceRecord.scanned_at.desc()).all()

    return render_template(
        'faculty/attendance.html',
        user=user,
        dept=dept,
        events_list=events_list,
        selected_event=selected_event,
        records=records
    )


@faculty_bp.route('/announcements')
@faculty_required
def announcements():
    user = get_current_user()
    dept = user.faculty_profile.department if user.faculty_profile else 'General'

    announcements_list = Announcement.query.filter(
        Announcement.is_active == True,
        or_(
            Announcement.target_audience == TargetAudience.ALL,
            Announcement.target_audience == 'FACULTY',
            (Announcement.target_audience == TargetAudience.DEPARTMENT) & (Announcement.target_department == dept)
        )
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).all()

    return render_template(
        'faculty/announcements.html',
        user=user,
        dept=dept,
        announcements=announcements_list
    )
