"""
Campus Flow - Automatic Empty Slots Capacity Notification Service
Monitors events as they reach their start time or when started by an organizer,
and notifies the responsible HOD if unfilled/empty registration slots exist.
"""
import logging
import threading
import time
from datetime import datetime

from models import (
    db, Event, EventStatus, Notification, NotificationType,
    EventNotificationLog, User, UserRole
)
from services.email_service import send_empty_slots_hod_email

logger = logging.getLogger("CampusFlow.CapacityNotification")

_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False


def get_hod_for_department(dept_code):
    """
    Finds the HOD user associated with a given department code from existing
    user, role, and department data without creating any duplicates.
    Priority:
    1. CollegeDepartment (matching code, normalized code, or name) -> dept.hod or dept.hod_id
    2. User with role == 'hod' whose FacultyProfile.department matches
    3. User with role == 'hod' whose email contains hod.<dept_code>
    """
    if not dept_code:
        return None
    from models import User, UserRole, FacultyProfile, CollegeDepartment, Department

    norm = Department.normalize_code(dept_code)

    # 1. Look up in CollegeDepartment by code, normalized code, or name
    college_dept = CollegeDepartment.query.filter(
        (CollegeDepartment.code == dept_code) |
        (CollegeDepartment.code == norm) |
        (CollegeDepartment.name == dept_code)
    ).first()

    if college_dept:
        if getattr(college_dept, 'hod', None):
            return college_dept.hod
        if college_dept.hod_id:
            h = User.query.get(college_dept.hod_id)
            if h:
                return h

    # 2. Look up User where role == HOD and FacultyProfile.department matches
    hod_user = User.query.filter(
        User.role == UserRole.HOD
    ).join(FacultyProfile, FacultyProfile.user_id == User.id, isouter=True).filter(
        (FacultyProfile.department == dept_code) |
        (FacultyProfile.department == norm) |
        (FacultyProfile.department == getattr(college_dept, 'name', None)) |
        (FacultyProfile.department == getattr(college_dept, 'code', None))
    ).first()

    if hod_user:
        return hod_user

    # 3. Fallback: check User with email containing hod.<dept>
    hod_fallback = User.query.filter(
        User.role == UserRole.HOD,
        User.email.ilike(f"%hod.{dept_code.lower()}%")
    ).first()

    return hod_fallback


def notify_hod_event_started(event, force=False):
    """
    Called ONLY when the Organizer manually starts an event.
    Calculates at that exact moment:
    - Total event slots
    - Online registered students
    - On-spot registrations
    - Total occupied slots
    - Remaining/empty slots

    DEPARTMENT-WISE HOD NOTIFICATION:
    - Identifies the department of every registered/spot-registered student.
    - Groups the registrations department-wise.
    - Finds the HOD associated with each department from existing data.
    - Sends the notification ONLY to the respective department HODs.
    - Does NOT send every department's info to unrelated HODs.
    - If an event has students from only one department, notifies only that department's HOD.
    - If an event has no students from a particular department, does not notify that department's HOD.
    - Prevents duplicate notifications if clicked again or refreshed.

    Notification Format:
    Event Started: [Event Name]
    Department: [Department Name]
    Total Event Slots: [number]
    Online Registrations: [number]
    On-Spot Registrations: [number]
    Total Occupied: [number]
    Empty Slots: [number]

    Returns:
        list: Dispatched notification summaries for each department.
    """
    if not event:
        return []

    # Do not alert for cancelled, rejected, draft, or completed events
    if event.status in (EventStatus.CANCELLED, EventStatus.REJECTED, EventStatus.DRAFT,
                        EventStatus.COMPLETED, 'EVENT_COMPLETED'):
        logger.info(f"[EMPTY_SLOT_CHECK] Event ID {event.id} ('{event.title}') is in {event.status} state. Skipping.")
        return []

    now = datetime.utcnow()
    if event.end_time and event.end_time <= now:
        logger.info(f"[EMPTY_SLOT_CHECK] Event ID {event.id} ('{event.title}') has already ended. Skipping.")
        return []

    # Duplicate prevention: Check if alert was already dispatched for this event
    if event.empty_slot_notification_sent and not force:
        logger.info(f"[EMPTY_SLOT_CHECK] Capacity alert already dispatched for Event ID {event.id}. Skipping duplicate.")
        return []

    from models import (
        User, UserRole, FacultyProfile, CollegeDepartment, Department,
        EventRegistration, RegistrationStatus
    )

    # 1. Total event capacity: Every event has ONE Total Event Capacity (event.max_participants)
    total_event_slots = event.max_participants or 0

    # 2. Get all confirmed registrations
    confirmed_regs = event.registrations.filter(
        EventRegistration.status == RegistrationStatus.CONFIRMED
    ).all()

    # If the event is fully booked (0 empty slots), do not dispatch empty slots capacity alerts
    total_confirmed = len(confirmed_regs)
    if total_event_slots > 0 and total_confirmed >= total_event_slots:
        logger.info(
            f"[EMPTY_SLOT_CHECK] Event #{event.id} is fully booked ({total_confirmed}/{total_event_slots}). "
            f"No empty slot notifications to dispatch."
        )
        return []

    # 3. Group registrations department-wise
    # dept_groups: { dept_code: {'online': count, 'spot': count} }
    dept_groups = {}
    for reg in confirmed_regs:
        st_dept = None
        if reg.student and reg.student.student_profile and reg.student.student_profile.department:
            st_dept = reg.student.student_profile.department.strip()
        elif reg.student and getattr(reg.student, 'department', None):
            st_dept = reg.student.department.strip()

        dept_code = Department.normalize_code(st_dept) if st_dept else (Department.normalize_code(event.department) or 'General')
        if not dept_code:
            dept_code = 'General'

        if dept_code not in dept_groups:
            dept_groups[dept_code] = {'online': 0, 'spot': 0}

        reg_type = getattr(reg, 'registration_type', 'ONLINE') or 'ONLINE'
        if reg_type == 'SPOT':
            dept_groups[dept_code]['spot'] += 1
        else:
            dept_groups[dept_code]['online'] += 1

    # If no students registered at all, include event's primary hosting department
    if not dept_groups and event.department:
        primary_code = Department.normalize_code(event.department) or event.department
        dept_groups[primary_code] = {'online': 0, 'spot': 0}

    # 4. Determine department quota for empty slots calculation
    allowed_list = []
    if event.allowed_departments and event.allowed_departments != 'ALL':
        allowed_list = [Department.normalize_code(d.strip()) for d in event.allowed_departments.split(',') if d.strip()]

    num_depts = len(allowed_list) if len(allowed_list) > 1 else len(dept_groups)
    dept_quota = (total_event_slots // num_depts) if num_depts > 1 else total_event_slots

    dispatched = []

    for dept_code, counts in dept_groups.items():
        online_count = counts['online']
        spot_count = counts['spot']
        occupied_count = online_count + spot_count
        empty_slots = max(0, dept_quota - occupied_count)

        # Resolve responsible HOD for this specific department
        hod = get_hod_for_department(dept_code)
        if not hod and dept_code == Department.normalize_code(event.department):
            hod = event.get_responsible_hod()

        if not hod:
            logger.warning(
                f"[HOD_NOT_FOUND] Could not resolve HOD for department '{dept_code}' in Event #{event.id}."
            )
            continue

        # Prevent duplicate notification to this HOD
        existing_log = EventNotificationLog.query.filter_by(
            event_id=event.id,
            notification_type=NotificationType.EVENT_CAPACITY_ALERT,
            recipient_user_id=hod.id
        ).first()

        existing_notif = Notification.query.filter_by(
            user_id=hod.id,
            event_id=event.id,
            type=NotificationType.EVENT_CAPACITY_ALERT,
            is_expired=False
        ).first()

        if (existing_log or existing_notif) and not force:
            logger.info(f"[HOD_NOTIFICATION_ALREADY_SENT] Capacity alert already exists for Event #{event.id} and HOD {hod.email}. Skipping.")
            continue

        dept_obj = CollegeDepartment.query.filter(
            (CollegeDepartment.code == dept_code) | (CollegeDepartment.name == dept_code)
        ).first()
        dept_display = dept_obj.name if dept_obj else Department.CODE_TO_NAME.get(dept_code, dept_code)

        notif_title = f"Event Started: {event.title}"
        notif_message = (
            f"Event Started: {event.title}\n"
            f"Department: {dept_display}\n"
            f"Total Event Slots: {total_event_slots}\n"
            f"Online Registrations: {online_count}\n"
            f"On-Spot Registrations: {spot_count}\n"
            f"Total Occupied: {occupied_count}\n"
            f"Empty Slots: {empty_slots}"
        )

        in_app_notif = Notification(
            user_id=hod.id,
            title=notif_title,
            message=notif_message,
            type=NotificationType.EVENT_CAPACITY_ALERT,
            link=f"/events/{event.id}",
            event_id=event.id,
            expires_at=event.end_time,
            is_expired=False,
            is_read=False,
            created_at=now
        )
        db.session.add(in_app_notif)

        log_entry = EventNotificationLog(
            event_id=event.id,
            notification_type=NotificationType.EVENT_CAPACITY_ALERT,
            recipient_user_id=hod.id,
            sent_at=now,
            status='SENT',
            details=f"Dept: {dept_code} | Total: {total_event_slots} | Online: {online_count} | Spot: {spot_count} | Occupied: {occupied_count} | Empty: {empty_slots}"
        )
        db.session.add(log_entry)

        # Dispatch Email
        email_sent = False
        try:
            from services.email_service import send_dept_event_started_hod_email
            email_sent = send_dept_event_started_hod_email(
                hod=hod,
                event=event,
                dept_name=dept_display,
                total_slots=total_event_slots,
                online_count=online_count,
                spot_count=spot_count,
                occupied_count=occupied_count,
                empty_slots=empty_slots
            )
        except Exception as mail_err:
            logger.error(f"[HOD_EMAIL_FAILED] Failed to send email to HOD {hod.email}: {mail_err}")

        dispatched.append({
            'hod_id': hod.id,
            'hod_email': hod.email,
            'department': dept_code,
            'dept_display': dept_display,
            'total_slots': total_event_slots,
            'online_count': online_count,
            'spot_count': spot_count,
            'occupied_count': occupied_count,
            'empty_slots': empty_slots,
            'in_app_id': in_app_notif.id,
            'email_sent': email_sent
        })

    # Mark global event flag as sent
    event.empty_slot_notification_sent = True
    db.session.add(event)
    db.session.commit()

    logger.info(f"[EVENT_STARTED_NOTIFIED] Dispatched notifications for event #{event.id} to {len(dispatched)} department HOD(s).")
    return dispatched



def cleanup_expired_capacity_notifications():
    """
    Cleans up expired or cancelled event empty-slot capacity notifications.
    Strictly touches ONLY NotificationType.EVENT_CAPACITY_ALERT notifications.
    Requirements satisfied:
    - Once the event's end time has passed, automatically delete/archive the corresponding
      "empty slots" alert from the HOD notification panel.
    - If the event is cancelled, also remove the active empty-slot alert for that event.
    - When expires_at <= current IST time, delete the notification from the HOD notification panel.
    - Do NOT delete unrelated HOD notifications.
    - Do NOT affect attendance records, registrations, event data, or other notifications.
    - Timezone handling consistent with India Standard Time (IST).

    Returns:
        int: Number of capacity notifications cleaned up.
    """
    from services.timezone_service import get_current_ist_time, to_ist
    now_utc = datetime.utcnow()
    current_ist = get_current_ist_time()

    alerts = Notification.query.filter_by(type=NotificationType.EVENT_CAPACITY_ALERT).all()
    cleaned_count = 0

    for alert in alerts:
        should_clean = False

        # 1. Check alert's expires_at against current IST time (and UTC)
        if alert.expires_at:
            exp_ist = to_ist(alert.expires_at)
            if exp_ist and exp_ist <= current_ist:
                should_clean = True
            elif alert.expires_at <= now_utc:
                should_clean = True

        # 2. Check associated event status and end_time
        if not should_clean and alert.event_id:
            event = alert.event or Event.query.get(alert.event_id)
            if event:
                if event.status in (EventStatus.CANCELLED, EventStatus.REJECTED, EventStatus.COMPLETED, 'EVENT_COMPLETED'):
                    should_clean = True
                elif event.end_time:
                    end_ist = to_ist(event.end_time)
                    if end_ist and end_ist <= current_ist:
                        should_clean = True
                    elif event.end_time <= now_utc:
                        should_clean = True

        if should_clean:
            logger.info(f"[CAPACITY_ALERT_CLEANUP] Removing expired/cancelled alert #{alert.id} for Event #{alert.event_id}")
            alert.is_expired = True
            db.session.delete(alert)
            cleaned_count += 1

    if cleaned_count > 0:
        db.session.commit()
        logger.info(f"[CAPACITY_ALERT_CLEANUP] Successfully cleaned up {cleaned_count} capacity alert(s).")
    return cleaned_count


def remove_event_capacity_alerts(event_id):
    """
    Immediately removes active empty-slot alerts for a specific event (e.g. when an event is cancelled).
    Strictly affects only NotificationType.EVENT_CAPACITY_ALERT for the specified event.
    """
    if not event_id:
        return 0
    alerts = Notification.query.filter_by(
        type=NotificationType.EVENT_CAPACITY_ALERT,
        event_id=event_id
    ).all()
    count = len(alerts)
    for a in alerts:
        a.is_expired = True
        db.session.delete(a)
    if count > 0:
        db.session.commit()
        logger.info(f"[CAPACITY_ALERT_CANCELLED] Removed {count} active capacity alert(s) for Event #{event_id}")
    return count


def update_event_capacity_alert_expiration(event):
    """
    Recalculates the alert expiration time using the updated event end time
    when the event date/time is edited.
    If the updated end time has already passed or event is cancelled, cleans it up immediately.
    """
    if not event or not event.id:
        return 0
    from services.timezone_service import get_current_ist_time, to_ist, format_ist_datetime
    current_ist = get_current_ist_time()
    now_utc = datetime.utcnow()

    # If event was cancelled, rejected, or completed
    if event.status in (EventStatus.CANCELLED, EventStatus.REJECTED, EventStatus.COMPLETED, 'EVENT_COMPLETED'):
        return remove_event_capacity_alerts(event.id)

    # If updated end time has already passed in IST
    if event.end_time:
        end_ist = to_ist(event.end_time)
        if (end_ist and end_ist <= current_ist) or (event.end_time <= now_utc):
            return remove_event_capacity_alerts(event.id)

    alerts = Notification.query.filter_by(
        type=NotificationType.EVENT_CAPACITY_ALERT,
        event_id=event.id
    ).all()

    updated_count = 0
    start_time_ist = format_ist_datetime(event.start_time) if event.start_time else "N/A"
    for alert in alerts:
        alert.expires_at = event.end_time
        alert.is_expired = False
        # Update start time line in message if changed
        if "Event Start Time:" in alert.message:
            import re
            alert.message = re.sub(r'Event Start Time: [^\n]+', f'Event Start Time: {start_time_ist}', alert.message)
        updated_count += 1

    if updated_count > 0:
        db.session.commit()
        logger.info(f"[CAPACITY_ALERT_UPDATED] Recalculated alert expiration for Event #{event.id} to {event.end_time}")
    return updated_count


def check_and_notify_empty_slots(app=None):
    """
    Background maintenance task:
    - Cleans up any expired capacity alerts where expires_at <= current IST time or event has ended.
    - NOTE: Events do NOT start automatically based on date or time.
    - Only the Organizer can manually click the "Start Event" button.
    - Notifications are NOT triggered when the event merely reaches its scheduled start time.
    Returns:
        list: Empty list (manual trigger only)
    """
    # Clean up any expired capacity notifications
    cleanup_expired_capacity_notifications()
    return []


def start_capacity_monitoring_scheduler(app, interval_seconds=60):
    """
    Launches a daemon background thread that periodically inspects starting events,
    triggers empty slot notifications to responsible HODs, and automatically purges
    expired notifications once the event end time has passed.
    """
    global _SCHEDULER_STARTED

    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            logger.info("Capacity monitoring scheduler is already running.")
            return

        import os
        # When running with Werkzeug reloader, only run in the child process to avoid duplicate threads
        if os.environ.get('WERKZEUG_RUN_MAIN') == 'false':
            return

        def _worker():
            logger.info(f"Capacity monitoring scheduler worker started (Interval: {interval_seconds}s).")
            # Wait a few seconds for initial server startup and db init
            time.sleep(5)
            while True:
                try:
                    with app.app_context():
                        cleanup_expired_capacity_notifications()
                        check_and_notify_empty_slots(app)
                except Exception as worker_err:
                    logger.error(f"Error in capacity monitoring scheduler loop: {worker_err}", exc_info=True)
                time.sleep(interval_seconds)

        thread = threading.Thread(target=_worker, name="CapacityMonitoringScheduler", daemon=True)
        thread.start()
        _SCHEDULER_STARTED = True
        logger.info("Capacity monitoring scheduler background thread launched.")


def notify_hod_spot_registration_closed(event, force=False):
    """
    Called ONLY when the organizer explicitly closes spot registration.
    Calculates unused spot slots:
        unused_spot_slots = spot_registration_slots - spot_registered
    
    If unused_spot_slots > 0 and notification not yet sent:
        Dispatches in-app notification and email to responsible HOD.
    If unused_spot_slots == 0:
        Does NOT notify HOD.
    Enforces duplicate prevention.
    """
    if not event:
        return None

    # Duplicate prevention: Check if spot empty slot notification was already sent
    if event.spot_empty_slot_notification_sent and not force:
        logger.info(f"[SPOT_NOTIFICATION] Spot empty slot notification already sent for event #{event.id}. Skipping duplicate.")
        return None

    spot_slots = event.spot_registration_slots or 0
    spot_registered = event.spot_registrations_count
    unused_slots = max(0, spot_slots - spot_registered)

    logger.info(
        f"[SPOT_REGISTRATION_CLOSED] Event #{event.id} ('{event.title}'): "
        f"Spot Slots: {spot_slots}, Registered: {spot_registered}, Unused: {unused_slots}"
    )

    # If no spot slots or no unused spot slots, do NOT notify HOD
    if spot_slots <= 0 or unused_slots <= 0:
        logger.info(f"[SPOT_NOTIFICATION] Event #{event.id} has 0 unused spot slots. Notification not required.")
        event.spot_empty_slot_notification_sent = True
        db.session.add(event)
        db.session.commit()
        return None

    # Resolve responsible Department HOD
    hod = event.get_responsible_hod()
    if not hod:
        logger.warning(
            f"[SPOT_NOTIFICATION] Event #{event.id} ('{event.title}') has {unused_slots} unused spot slots, "
            f"but no responsible HOD could be resolved for department '{event.department}'."
        )
        event.spot_empty_slot_notification_sent = True
        db.session.add(event)
        db.session.commit()
        return None

    now = datetime.utcnow()
    notification_title = f"Spot Registration Completed: {unused_slots} Unused Slots - {event.title}"
    notification_message = (
        f"Event: {event.title}\n"
        f"Spot Registration Completed\n"
        f"Spot slots provided by organizer: {spot_slots}\n"
        f"Students registered through spot registration: {spot_registered}\n"
        f"Unused spot slots: {unused_slots}\n\n"
        f"{unused_slots} spot-registration slots remained unused."
    )

    in_app_notif = Notification(
        user_id=hod.id,
        title=notification_title,
        message=notification_message,
        type=NotificationType.SPOT_CAPACITY_ALERT,
        link=f"/events/{event.id}",
        event_id=event.id,
        expires_at=event.end_time,
        is_expired=False,
        is_read=False,
        created_at=now
    )
    db.session.add(in_app_notif)

    # Log in EventNotificationLog for audit & duplicate protection
    log_entry = EventNotificationLog(
        event_id=event.id,
        notification_type=NotificationType.SPOT_CAPACITY_ALERT,
        recipient_user_id=hod.id,
        sent_at=now,
        status='SENT',
        details=f"Spot slots provided: {spot_slots}, Registered: {spot_registered}, Unused: {unused_slots}"
    )
    db.session.add(log_entry)

    # Mark event flag as sent
    event.spot_empty_slot_notification_sent = True
    db.session.add(event)
    db.session.commit()

    logger.info(f"[SPOT_NOTIFICATION_CREATED] In-app notification #{in_app_notif.id} created for HOD {hod.email}")

    # Dispatch Email to HOD (failsafe)
    email_dispatched = False
    try:
        from services.email_service import send_spot_empty_slots_hod_email
        email_dispatched = send_spot_empty_slots_hod_email(
            hod=hod,
            event=event,
            spot_slots=spot_slots,
            spot_registered=spot_registered,
            unused_slots=unused_slots
        )
    except Exception as e:
        logger.error(f"[SPOT_NOTIFICATION] Error sending spot empty slots email for event #{event.id}: {e}")

    return {
        'event_id': event.id,
        'hod_id': hod.id,
        'hod_email': hod.email,
        'spot_slots': spot_slots,
        'spot_registered': spot_registered,
        'unused_slots': unused_slots,
        'in_app_id': in_app_notif.id,
        'email_sent': email_dispatched
    }

