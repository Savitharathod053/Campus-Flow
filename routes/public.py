from datetime import datetime
from flask import Blueprint, render_template, request, url_for
from models import db, Event, EventStatus, EventType, EventRegistration, User, StudentProfile
from routes.auth import get_current_user

public_bp = Blueprint('public', __name__)

@public_bp.route('/')
def home():
    current_user = get_current_user()
    now = datetime.utcnow()

    # Featured upcoming events
    featured_events = Event.query.filter(
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN]),
        Event.end_time >= now
    ).order_by(Event.start_time.asc()).limit(6).all()

    # Recently added events
    recent_events = Event.query.filter(
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN])
    ).order_by(Event.created_at.desc()).limit(6).all()

    # Quick metrics for landing hero
    total_events_count = Event.query.filter(Event.status != EventStatus.DRAFT).count()
    total_registrations_count = EventRegistration.query.filter_by(status='CONFIRMED').count()
    total_students_count = StudentProfile.query.count()

    departments = ['Computer Science (CSE)', 'Information Technology (IT)', 'Electronics (ECE)', 'Mechanical (MECH)', 'Civil', 'Electrical (EEE)', 'General / All']
    event_types = EventType.CHOICES

    return render_template(
        'public/index.html',
        featured_events=featured_events,
        recent_events=recent_events,
        total_events_count=total_events_count,
        total_registrations_count=total_registrations_count,
        total_students_count=total_students_count,
        departments=departments,
        event_types=event_types,
        current_user=current_user
    )


@public_bp.route('/events')
def events():
    current_user = get_current_user()
    now = datetime.utcnow()

    # Search & Filters
    search_query = request.args.get('q', '').strip()
    selected_type = request.args.get('type', '').strip()
    selected_dept = request.args.get('department', '').strip()
    selected_year = request.args.get('year', '').strip()
    pricing_filter = request.args.get('pricing', '').strip() # 'free', 'paid', or empty
    status_filter = request.args.get('status', 'upcoming') # 'upcoming', 'past', 'all'

    query = Event.query.filter(
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN, EventStatus.REGISTRATION_CLOSED, EventStatus.EVENT_COMPLETED])
    )

    if status_filter == 'upcoming':
        query = query.filter(Event.end_time >= now)
    elif status_filter == 'past':
        query = query.filter(Event.end_time < now)

    if search_query:
        query = query.filter(
            (Event.title.ilike(f'%{search_query}%')) | 
            (Event.description.ilike(f'%{search_query}%')) |
            (Event.venue.ilike(f'%{search_query}%')) |
            (Event.department.ilike(f'%{search_query}%'))
        )

    if selected_type and selected_type != 'ALL':
        query = query.filter(Event.event_type == selected_type)

    if selected_dept and selected_dept != 'ALL':
        query = query.filter(
            (Event.department.ilike(f'%{selected_dept}%')) | 
            (Event.allowed_departments == 'ALL') |
            (Event.allowed_departments.ilike(f'%{selected_dept}%'))
        )

    if selected_year and selected_year != 'ALL':
        query = query.filter(
            (Event.allowed_years == 'ALL') |
            (Event.allowed_years.ilike(f'%{selected_year}%'))
        )

    if pricing_filter == 'free':
        query = query.filter(Event.is_free == True)
    elif pricing_filter == 'paid':
        query = query.filter(Event.is_free == False)

    events_list = query.order_by(Event.start_time.asc()).all()

    departments = ['Computer Science (CSE)', 'Information Technology (IT)', 'Electronics (ECE)', 'Mechanical (MECH)', 'Civil', 'Electrical (EEE)', 'Biotechnology', 'Management']
    event_types = EventType.CHOICES

    return render_template(
        'public/events_list.html',
        events=events_list,
        search_query=search_query,
        selected_type=selected_type,
        selected_dept=selected_dept,
        selected_year=selected_year,
        pricing_filter=pricing_filter,
        status_filter=status_filter,
        departments=departments,
        event_types=event_types,
        current_user=current_user
    )


@public_bp.route('/events/<slug>')
def event_detail(slug):
    current_user = get_current_user()
    event = Event.query.filter_by(slug=slug).first_or_404()

    is_registered = False
    existing_registration = None
    is_eligible = True
    eligibility_message = "Eligible"

    if current_user and current_user.is_student:
        existing_registration = EventRegistration.query.filter_by(
            event_id=event.id,
            student_id=current_user.id
        ).first()
        is_registered = existing_registration is not None

        if current_user.student_profile:
            is_eligible, eligibility_message = event.check_student_eligibility(current_user.student_profile)

    # Active announcements for this event
    announcements = event.announcements

    return render_template(
        'public/event_detail.html',
        event=event,
        is_registered=is_registered,
        existing_registration=existing_registration,
        is_eligible=is_eligible,
        eligibility_message=eligibility_message,
        announcements=announcements,
        current_user=current_user
    )
