"""
Campus Flow - Multi-Session Attendance Service
Core business logic for session creation, QR scanning, time validation, duplicate prevention,
manual overrides, and matrix report calculations.
"""
from datetime import datetime, date, time
import logging
from models import (
    db, Event, EventRegistration, RegistrationStatus, AttendanceRecord,
    AttendanceSession, AttendanceSessionStatus, AttendanceStatus,
    VerificationMethod, User, StudentProfile
)

logger = logging.getLogger(__name__)

class AttendanceServiceError(Exception):
    """Custom exception for attendance business logic errors."""
    pass


def parse_time_str(time_val):
    """Helper to parse time string in HH:MM or HH:MM:SS format."""
    if not time_val:
        return None
    if isinstance(time_val, time):
        return time_val
    try:
        parts = str(time_val).strip().split(':')
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) > 2 else 0
        return time(hour, minute, second)
    except Exception:
        return None


def parse_date_str(date_val):
    """Helper to parse date string in YYYY-MM-DD format."""
    if not date_val:
        return None
    if isinstance(date_val, (date, datetime)):
        return date_val.date() if isinstance(date_val, datetime) else date_val
    try:
        return datetime.strptime(str(date_val).strip()[:10], '%Y-%m-%d').date()
    except Exception:
        return None


def create_or_update_event_sessions(event, session_data_list):
    """
    Creates or updates attendance sessions for an event.
    session_data_list is a list of dicts:
    [{'id': optional, 'session_name': str, 'event_date': str/date, 'start_time': str/time, 'end_time': str/time, 'status': str}]
    """
    existing_sessions = {s.id: s for s in event.attendance_sessions.all()}
    kept_session_ids = set()

    session_num = 1
    for sdata in session_data_list:
        name = str(sdata.get('session_name', '')).strip()
        if not name:
            name = f"Session {session_num}"

        s_id = sdata.get('id')
        session_obj = existing_sessions.get(int(s_id)) if s_id else None

        if not session_obj:
            session_obj = AttendanceSession(
                event_id=event.id,
                session_name=name,
                session_number=session_num,
                event_date=parse_date_str(sdata.get('event_date')),
                start_time=parse_time_str(sdata.get('start_time')),
                end_time=parse_time_str(sdata.get('end_time')),
                status=sdata.get('status', AttendanceSessionStatus.ACTIVE)
            )
            db.session.add(session_obj)
        else:
            session_obj.session_name = name
            session_obj.session_number = session_num
            session_obj.event_date = parse_date_str(sdata.get('event_date'))
            session_obj.start_time = parse_time_str(sdata.get('start_time'))
            session_obj.end_time = parse_time_str(sdata.get('end_time'))
            if 'status' in sdata and sdata['status']:
                session_obj.status = sdata['status']
            kept_session_ids.add(session_obj.id)

        session_num += 1

    # Remove deleted sessions that are no longer in the list
    for s_id, s_obj in existing_sessions.items():
        if s_id not in kept_session_ids and len(kept_session_ids) > 0:
            db.session.delete(s_obj)

    db.session.commit()
    return event.attendance_sessions.all()


def record_session_attendance(event_id, session_id, registration_code, marked_by_user, allow_time_override=False):
    """
    Validates QR code and marks attendance for a specific session.
    
    Returns structured dict with status: 'success', 'duplicate', 'session_closed', 'invalid', 'mismatch', 'unconfirmed', 'unpaid'
    """
    event = Event.query.get(event_id)
    if not event:
        return {'status': 'invalid', 'message': 'Event not found.'}, 404

    # Clean raw code
    clean_code = str(registration_code).strip()
    for prefix in ['CAMPUSFLOW-TICKET:', 'FASTFEST-TICKET:', 'CAMPUSFLOW-TICKET', 'FASTFEST-TICKET']:
        if clean_code.upper().startswith(prefix):
            clean_code = clean_code[len(prefix):].strip()
    clean_code = clean_code.lstrip(':').strip()

    # 1. Search for registration by registration_code (case-insensitive) for this event
    registration = EventRegistration.query.filter(
        EventRegistration.event_id == event.id,
        db.func.upper(EventRegistration.registration_code) == clean_code.upper()
    ).first()

    # 2. Check if code matches a registration for a different event (to return a clear mismatch)
    if not registration:
        other_reg = EventRegistration.query.filter(
            db.func.upper(EventRegistration.registration_code) == clean_code.upper()
        ).first()
        if other_reg:
            return {
                'status': 'mismatch',
                'message': f"This ticket belongs to '{other_reg.event.title}', not '{event.title}'."
            }, 400

    # 3. Fallback: Search by Student Roll Number or Email for this event
    if not registration:
        reg_by_roll = EventRegistration.query.join(User, EventRegistration.student_id == User.id)\
            .join(StudentProfile, StudentProfile.user_id == User.id, isouter=True)\
            .filter(
                EventRegistration.event_id == event.id,
                db.func.upper(StudentProfile.roll_number) == clean_code.upper()
            ).first()
        if reg_by_roll:
            registration = reg_by_roll
        else:
            reg_by_email = EventRegistration.query.join(User, EventRegistration.student_id == User.id)\
                .filter(
                    EventRegistration.event_id == event.id,
                    db.func.lower(User.email) == clean_code.lower()
                ).first()
            if reg_by_email:
                registration = reg_by_email

    if not registration:
        return {'status': 'invalid', 'message': f"Ticket or participant '{clean_code}' was not found in the system."}, 404

    student = registration.student
    profile = student.student_profile if student else None

    # Resolve session
    session = None
    if session_id:
        session = AttendanceSession.query.filter_by(id=session_id, event_id=event.id).first()
    if not session:
        # Fallback to first active session or default session
        session = event.attendance_sessions.first()

    if not session:
        # Create a default session on the fly if none exists
        session = AttendanceSession(
            event_id=event.id,
            session_name="General Attendance",
            session_number=1,
            status=AttendanceSessionStatus.ACTIVE
        )
        db.session.add(session)
        db.session.flush()

    # Validate confirmation status
    if not registration.is_confirmed:
        return {
            'status': 'unconfirmed',
            'message': f"Registration is {registration.status}. Entry passes are only valid once confirmed.",
            'student_name': student.name if student else 'N/A',
            'roll_number': profile.roll_number if profile and profile.roll_number else 'N/A',
            'department': profile.department if profile and profile.department else 'N/A',
            'year': profile.year if profile and profile.year else 'N/A',
            'section': profile.section if profile and profile.section else 'N/A',
            'team_name': registration.team.team_name if registration.team else None,
            'session_name': session.session_name,
            'scanned_at': datetime.utcnow().strftime('%I:%M %p')
        }, 400

    # Validate payment if required
    if not registration.is_paid:
        team_name = registration.team.team_name if registration.team else None
        msg = f"Team payment for '{team_name}' is pending. Please complete fee payment." if team_name else "Registration fee payment is pending for this participant."
        return {
            'status': 'unpaid',
            'message': msg,
            'student_name': student.name if student else 'N/A',
            'roll_number': profile.roll_number if profile and profile.roll_number else 'N/A',
            'department': profile.department if profile and profile.department else 'N/A',
            'year': profile.year if profile and profile.year else 'N/A',
            'section': profile.section if profile and profile.section else 'N/A',
            'team_name': team_name,
            'session_name': session.session_name,
            'scanned_at': datetime.utcnow().strftime('%I:%M %p')
        }, 400

    # Time Validation
    if not allow_time_override:
        is_active, time_msg = session.is_time_active()
        if not is_active:
            return {
                'status': 'session_closed',
                'message': time_msg,
                'student_name': student.name if student else 'N/A',
                'roll_number': profile.roll_number if profile and profile.roll_number else 'N/A',
                'department': profile.department if profile and profile.department else 'N/A',
                'year': profile.year if profile and profile.year else 'N/A',
                'section': profile.section if profile and profile.section else 'N/A',
                'team_name': registration.team.team_name if registration.team else None,
                'session_name': session.session_name,
                'session_id': session.id,
                'scanned_at': datetime.utcnow().strftime('%I:%M %p'),
                'can_override': True
            }, 200

    # Duplicate Check for this session
    existing_att = AttendanceRecord.query.filter_by(
        event_id=event.id,
        session_id=session.id,
        student_id=student.id
    ).first()

    if existing_att and existing_att.status == AttendanceStatus.PRESENT:
        return {
            'status': 'duplicate',
            'message': f"{student.name} is already marked PRESENT for '{session.session_name}'.",
            'student_name': student.name,
            'roll_number': profile.roll_number if profile else 'N/A',
            'department': profile.department if profile else 'N/A',
            'year': profile.year if profile and profile.year else 'N/A',
            'section': profile.section if profile and profile.section else 'N/A',
            'team_name': registration.team.team_name if registration.team else None,
            'session_name': session.session_name,
            'scanned_at': existing_att.scanned_at.strftime('%I:%M %p')
        }, 200

    # Create / Update attendance record
    if not existing_att:
        att_record = AttendanceRecord(
            registration_id=registration.id,
            event_id=event.id,
            student_id=student.id,
            session_id=session.id,
            marked_by_id=marked_by_user.id if marked_by_user else None,
            verification_method=VerificationMethod.QR_SCAN,
            status=AttendanceStatus.PRESENT,
            scanned_at=datetime.utcnow()
        )
        db.session.add(att_record)
    else:
        existing_att.status = AttendanceStatus.PRESENT
        existing_att.scanned_at = datetime.utcnow()
        existing_att.marked_by_id = marked_by_user.id if marked_by_user else None
        existing_att.verification_method = VerificationMethod.QR_SCAN
        att_record = existing_att

    db.session.commit()

    # Calculate updated metrics
    attended_count = event.get_student_attended_count(student.id)
    total_sessions = event.total_sessions_count
    student_percentage = event.get_student_attendance_percentage(student.id)
    session_present_count = session.present_count

    return {
        'status': 'success',
        'message': f"Attendance recorded for {student.name} ({session.session_name})",
        'student_name': student.name,
        'roll_number': profile.roll_number if profile else 'N/A',
        'department': profile.department if profile else 'N/A',
        'year': profile.year if profile else 'N/A',
        'section': profile.section if profile else 'N/A',
        'team_name': registration.team.team_name if registration.team else None,
        'session_id': session.id,
        'session_name': session.session_name,
        'session_present_count': session_present_count,
        'student_attended_sessions': attended_count,
        'total_sessions': total_sessions,
        'student_percentage': student_percentage,
        'is_satisfied': event.is_student_attendance_satisfied(student.id),
        'scanned_at': att_record.scanned_at.strftime('%I:%M %p')
    }, 200


def manual_override_attendance(event_id, session_id, student_id, new_status, marked_by_user, remarks=None):
    """
    Manually modifies attendance for a student for a specific session with audit tracking.
    """
    event = Event.query.get_or_404(event_id)
    session = AttendanceSession.query.filter_by(id=session_id, event_id=event.id).first_or_404()
    student = User.query.get_or_404(student_id)

    registration = EventRegistration.query.filter_by(event_id=event.id, student_id=student.id).first()
    if not registration:
        raise AttendanceServiceError("Student is not registered for this event.")

    record = AttendanceRecord.query.filter_by(
        event_id=event.id,
        session_id=session.id,
        student_id=student.id
    ).first()

    if not record:
        record = AttendanceRecord(
            registration_id=registration.id,
            event_id=event.id,
            student_id=student.id,
            session_id=session.id,
            marked_by_id=marked_by_user.id if marked_by_user else None,
            verification_method=VerificationMethod.MANUAL,
            status=new_status,
            remarks=remarks or f"Manually marked as {new_status} by {marked_by_user.name if marked_by_user else 'Admin'}",
            scanned_at=datetime.utcnow()
        )
        db.session.add(record)
    else:
        record.status = new_status
        record.verification_method = VerificationMethod.MANUAL
        record.marked_by_id = marked_by_user.id if marked_by_user else None
        record.remarks = remarks or f"Manually changed to {new_status} by {marked_by_user.name if marked_by_user else 'Admin'}"
        record.scanned_at = datetime.utcnow()

    db.session.commit()
    return record


def calculate_event_attendance_matrix(event):
    """
    Calculates the complete participant x session attendance matrix for reports and organizer dashboard.
    """
    sessions = event.attendance_sessions.all()
    if not sessions:
        # Default single session
        sessions = [AttendanceSession(
            id=0,
            event_id=event.id,
            session_name="General Attendance",
            session_number=1,
            status=AttendanceSessionStatus.ACTIVE
        )]

    registrations = event.registrations.filter_by(status=RegistrationStatus.CONFIRMED).all()
    total_sessions_count = len(sessions)

    # Pre-fetch all attendance records for this event
    all_records = AttendanceRecord.query.filter_by(event_id=event.id).all()
    # Map (student_id, session_id) -> AttendanceRecord
    record_map = {(r.student_id, r.session_id or 0): r for r in all_records}

    matrix = []
    for reg in registrations:
        student = reg.student
        profile = student.student_profile if student else None
        
        session_statuses = []
        attended_count = 0

        for s in sessions:
            rec = record_map.get((student.id, s.id if s.id != 0 else (all_records[0].session_id if all_records else 0)))
            if not rec:
                # Also check with session_id None for legacy
                rec = record_map.get((student.id, None))

            is_present = rec is not None and rec.status == AttendanceStatus.PRESENT
            if is_present:
                attended_count += 1
            session_statuses.append({
                'session_id': s.id,
                'session_name': s.session_name,
                'is_present': is_present,
                'scanned_at': rec.scanned_at if rec else None,
                'method': rec.verification_method if rec else None
            })

        percentage = round((attended_count / total_sessions_count) * 100.0, 2) if total_sessions_count > 0 else 0.0
        is_satisfied = percentage >= event.min_attendance_percentage if event.min_attendance_percentage > 0 else attended_count > 0

        matrix.append({
            'registration': reg,
            'student': student,
            'profile': profile,
            'team': reg.team,
            'session_statuses': session_statuses,
            'attended_count': attended_count,
            'total_sessions': total_sessions_count,
            'percentage': percentage,
            'is_satisfied': is_satisfied
        })

    return {
        'sessions': sessions,
        'matrix': matrix,
        'total_participants': len(registrations),
        'min_attendance_percentage': event.min_attendance_percentage
    }
