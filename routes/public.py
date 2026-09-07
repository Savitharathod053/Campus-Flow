from datetime import datetime
from flask import Blueprint, render_template, request, url_for
from models import db, Event, EventStatus, EventType, EventRegistration, User, StudentProfile, Department
from routes.auth import get_current_user

public_bp = Blueprint('public', __name__)

@public_bp.route('/')
def home():
    current_user = get_current_user()
    now = datetime.utcnow()

    # Featured upcoming events (strictly dual-approved, published, active, non-expired)
    featured_candidates = Event.query.filter(
        Event.is_published == True,
        Event.hod_approved == True,
        Event.dean_approved == True,
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN, EventStatus.UPCOMING]),
        Event.start_time > now,
        Event.end_time > now,
        Event.registration_deadline > now,
        Event.status.notin_([EventStatus.COMPLETED, 'EVENT_COMPLETED', EventStatus.CANCELLED, EventStatus.REJECTED])
    ).order_by(Event.start_time.asc()).limit(12).all()
    featured_events = [
        e for e in featured_candidates 
        if not e.is_completed and not e.is_expired and not e.is_deadline_passed and e.is_upcoming
    ][:6]

    # Recently added events (strictly dual-approved, published, active, non-expired)
    recent_candidates = Event.query.filter(
        Event.is_published == True,
        Event.hod_approved == True,
        Event.dean_approved == True,
        Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN, EventStatus.UPCOMING, EventStatus.ONGOING]),
        Event.end_time > now,
        Event.status.notin_([EventStatus.COMPLETED, 'EVENT_COMPLETED', EventStatus.CANCELLED, EventStatus.REJECTED])
    ).order_by(Event.created_at.desc()).limit(12).all()
    recent_events = [
        e for e in recent_candidates 
        if not e.is_completed and not e.is_expired
    ][:6]

    # Quick metrics for landing hero
    total_events_count = Event.query.filter(Event.is_published == True).count()
    total_registrations_count = EventRegistration.query.filter_by(status='CONFIRMED').count()
    total_students_count = StudentProfile.query.count()

    departments = Department.CHOICES
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

    # STRICT: Only show events that have passed both HOD and Dean dual approval
    query = Event.query.filter(
        Event.is_published == True,
        Event.hod_approved == True,
        Event.dean_approved == True,
        Event.status.in_([
            EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN,
            EventStatus.REGISTRATION_CLOSED, EventStatus.UPCOMING,
            EventStatus.ONGOING, EventStatus.COMPLETED, 'EVENT_COMPLETED'
        ])
    )

    if status_filter == 'upcoming':
        query = query.filter(
            Event.start_time > now,
            Event.end_time > now,
            Event.status.notin_([EventStatus.COMPLETED, 'EVENT_COMPLETED', EventStatus.CANCELLED, EventStatus.REJECTED])
        )
    elif status_filter == 'past':
        query = query.filter(db.or_(Event.end_time <= now, Event.status.in_([EventStatus.COMPLETED, 'EVENT_COMPLETED'])))

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
        if selected_dept.upper() in ['CIVIL', 'CIVILS']:
            query = query.filter(
                (Event.department.ilike('%CIVIL%')) | 
                (Event.allowed_departments == 'ALL') |
                (Event.allowed_departments.ilike('%CIVIL%'))
            )
        else:
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

    departments = Department.CHOICES
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

    # MANDATORY DUAL APPROVAL VALIDATION:
    # If the event is not approved by both HOD and Dean, public/students cannot view it.
    if not event.is_published or not (event.hod_approved and event.dean_approved):
        is_authorized_viewer = (
            current_user and (
                current_user.is_super_admin or
                current_user.is_students_affairs_dean or
                (current_user.is_hod and (event.department_id == current_user.id or event.department == (current_user.faculty_profile.department if current_user.faculty_profile else ''))) or
                current_user.id == event.organizer_id
            )
        )
        if not is_authorized_viewer:
            abort(404)

    is_registered = False
    existing_registration = None
    existing_team = None
    is_eligible = True
    eligibility_message = "Eligible"

    if current_user and current_user.is_student:
        existing_registration = EventRegistration.query.filter_by(
            event_id=event.id,
            student_id=current_user.id
        ).first()
        is_registered = existing_registration is not None

        if existing_registration and existing_registration.team_id:
            existing_team = existing_registration.team

        if current_user.student_profile:
            is_eligible, eligibility_message = event.check_student_eligibility(current_user.student_profile)

    # Active announcements for this event
    announcements = event.announcements

    return render_template(
        'public/event_detail.html',
        event=event,
        is_registered=is_registered,
        existing_registration=existing_registration,
        existing_team=existing_team,
        is_eligible=is_eligible,
        eligibility_message=eligibility_message,
        announcements=announcements,
        current_user=current_user
    )
