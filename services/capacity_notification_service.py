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


def notify_hod_event_started(event, force=False):
    """
    Evaluates an active/started event and dispatches an empty slots capacity notification
    to the responsible Department HOD if unfilled slots remain.

    Sequence:
    1. Validate event status & state.
    2. Enforce duplicate prevention via empty_slot_notification_sent and EventNotificationLog.
    3. Calculate total_capacity, confirmed_count, and empty_slots.
    4. Log EVENT_STARTED and EMPTY_SLOT_CHECK.
    5. If empty_slots <= 0, mark processed and return.
    6. Resolve responsible HOD for event's department.
    7. Create In-App Notification for HOD.
    8. Create EventNotificationLog record.
    9. Mark event.empty_slot_notification_sent = True.
    10. Dispatch Email notification if email service is active.

    Returns:
        dict or None: Result metadata if notification was created, None otherwise.
    """
    if not event:
        return None

    # Do not alert for cancelled, rejected, or completed events
    if event.status in (EventStatus.CANCELLED, EventStatus.REJECTED, EventStatus.DRAFT,
                        EventStatus.COMPLETED, 'EVENT_COMPLETED'):
        logger.info(f"[EMPTY_SLOT_CHECK] Event ID {event.id} ('{event.title}') is in {event.status} state. Skipping.")
        return None

    # Check if event end_time has already passed (alert must only be active during event)
    now = datetime.utcnow()
    if event.end_time and event.end_time <= now:
        logger.info(f"[EMPTY_SLOT_CHECK] Event ID {event.id} ('{event.title}') has already ended (end_time: {event.end_time}). Skipping notification.")
        return None

    # Duplicate prevention: Check if alert was already dispatched
    if event.empty_slot_notification_sent and not force:
        logger.info(f"[EMPTY_SLOT_CHECK] Capacity alert already dispatched for Event ID {event.id}. Skipping duplicate.")
        return None

    total_capacity = event.max_participants or 0
    confirmed_count = event.confirmed_registrations_count
    empty_slots = max(0, total_capacity - confirmed_count)

    logger.info(f"[EVENT_STARTED] Event ID {event.id} ('{event.title}') - Status: {event.status}")
    logger.info(
        f"[EMPTY_SLOT_CHECK] Event ID {event.id} ('{event.title}'): "
        f"Total Capacity: {total_capacity}, Confirmed: {confirmed_count}, Empty Slots: {empty_slots}"
    )

    # If no empty slots (fully booked / 0 empty slots), do NOT send notification
    if empty_slots <= 0:
        logger.info(f"[EMPTY_SLOT_CHECK] Event ID {event.id} has 0 empty slots (fully booked). Notification not required.")
        event.empty_slot_notification_sent = True
        db.session.add(event)
        db.session.commit()
        return None

    # Resolve responsible Department HOD
    hod = event.get_responsible_hod()
    if not hod:
        logger.warning(
            f"[HOD_IDENTIFIED] Event ID {event.id} ('{event.title}') has {empty_slots} empty slots, "
            f"but no responsible HOD could be resolved for department '{event.department}'."
        )
        # Mark as notified to avoid spamming unresolved logs every scheduler tick
        event.empty_slot_notification_sent = True
        db.session.add(event)
        db.session.commit()
        return None

    logger.info(f"[HOD_IDENTIFIED] Responsible HOD resolved: {hod.name} ({hod.email}, ID: {hod.id}) for Department '{event.department}'")

    # Enforce database unique constraint / duplicate log check
    existing_log = EventNotificationLog.query.filter_by(
        event_id=event.id,
        notification_type=NotificationType.EVENT_CAPACITY_ALERT,
        recipient_user_id=hod.id
    ).first()

    if existing_log and not force:
        logger.info(f"[HOD_NOTIFICATION_ALREADY_SENT] Capacity alert already logged for Event {event.id} and HOD {hod.id}. Skipping.")
        event.empty_slot_notification_sent = True
        db.session.add(event)
        db.session.commit()
        return None

    # Also check if an active (non-expired) in-app Notification already exists for this event and HOD
    existing_active_notif = Notification.query.filter_by(
        user_id=hod.id,
        event_id=event.id,
        type=NotificationType.EVENT_CAPACITY_ALERT,
        is_expired=False
    ).first()
    if existing_active_notif and not force:
        logger.info(f"[HOD_NOTIFICATION_ALREADY_SENT] Active in-app capacity alert already exists for Event {event.id} and HOD {hod.id}. Skipping.")
        event.empty_slot_notification_sent = True
        db.session.add(event)
        db.session.commit()
        return None

    from services.timezone_service import format_ist_datetime
    start_time_ist = format_ist_datetime(event.start_time) if event.start_time else "N/A"
    organizer_name = event.organizer.name if event.organizer else "Event Organizer"
    dept_display = event.department or (event.department_rel.name if event.department_rel else "Department")

    # 1. Create In-App Notification with configured event start time, empty slots, event_id and expires_at
    notification_title = f"🔔 Event Started (Event Capacity Alert): {event.title}"
    notification_message = (
        f"Event \"{event.title}\" (ID: #{event.id}) in {dept_display} has started and currently has {empty_slots} empty slots out of {total_capacity} ({empty_slots} empty slots remaining).\n"
        f"Department: {dept_display} | Organizer: {organizer_name} | "
        f"Confirmed Students: {confirmed_count} | Empty Slots: {empty_slots} | "
        f"Event Start Time: {start_time_ist}"
    )

    in_app_notif = Notification(
        user_id=hod.id,
        title=notification_title,
        message=notification_message,
        type=NotificationType.EVENT_CAPACITY_ALERT,
        link=f"/events/{event.id}",
        event_id=event.id,
        expires_at=event.end_time,
        is_expired=False,
        is_read=False,
        created_at=now
    )
    db.session.add(in_app_notif)

    # 2. Log in EventNotificationLog for audit & unique constraint guarantee
    log_entry = EventNotificationLog(
        event_id=event.id,
        notification_type=NotificationType.EVENT_CAPACITY_ALERT,
        recipient_user_id=hod.id,
        sent_at=now,
        status='SENT',
        details=f"Empty slots: {empty_slots}/{total_capacity} (Confirmed: {confirmed_count}, Organizer: {organizer_name})"
    )
    db.session.add(log_entry)

    # 3. Mark event flag as sent
    event.empty_slot_notification_sent = True
    db.session.add(event)

    db.session.commit()
    logger.info(f"[HOD_NOTIFICATION_CREATED] In-app notification #{in_app_notif.id} created for HOD {hod.email} (User ID: {hod.id}, Expires: {event.end_time})")

    # 4. Dispatch Email to HOD (failsafe, caught so in-app is never broken)
    email_dispatched = False
    try:
        email_dispatched = send_empty_slots_hod_email(
            hod=hod,
            event=event,
            empty_slots=empty_slots,
            total_capacity=total_capacity,
            confirmed_count=confirmed_count
        )
        if email_dispatched:
            logger.info(f"[HOD_EMAIL_SENT] Capacity notification email dispatched to HOD {hod.email}")
        else:
            logger.info(f"[HOD_EMAIL_SENT] Email dispatch skipped (no SMTP credentials or disabled)")
    except Exception as mail_err:
        logger.error(f"[HOD_EMAIL_FAILED] Failed to send capacity notification email to HOD {hod.email}: {mail_err}")

    return {
        'event_id': event.id,
        'event_title': event.title,
        'hod_id': hod.id,
        'hod_email': hod.email,
        'empty_slots': empty_slots,
        'total_capacity': total_capacity,
        'confirmed_students': confirmed_count,
        'in_app_notification_id': in_app_notif.id,
        'email_sent': email_dispatched
    }



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
    Scans events that have reached their start time (start_time <= now) or are active/started.
    - First cleans up any expired capacity alerts where expires_at <= current IST time or event has ended.
    - Transitions their lifecycle status to STARTED if appropriate.
    - If unfilled slots remain (empty_slots > 0), sends an in-app notification
      and an email to the responsible HOD.
    - Prevents duplicate alerts via event.empty_slot_notification_sent flag,
      EventNotificationLog records, and existing active Notification checks.
    Returns:
        list: Summary of processed event notifications
    """
    # 1. Clean up any expired capacity notifications
    cleanup_expired_capacity_notifications()

    now = datetime.utcnow()
    processed_alerts = []

    try:
        # Fetch events that have reached start time OR are currently marked STARTED/ONGOING
        events = Event.query.filter(
            Event.status.notin_([
                EventStatus.COMPLETED,
                'EVENT_COMPLETED',
                EventStatus.CANCELLED,
                EventStatus.REJECTED,
                EventStatus.DRAFT
            ]),
            (Event.start_time <= now) | (Event.status.in_([EventStatus.STARTED, EventStatus.ONGOING, 'Started']))
        ).all()

        for event in events:
            # Check dual approval / publishing
            if not event.is_published_and_approved:
                continue

            # Automatically transition status to STARTED if currently UPCOMING or APPROVED or REGISTRATION_OPEN
            if event.status in (EventStatus.UPCOMING, EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN):
                event.status = EventStatus.STARTED
                db.session.add(event)
                db.session.commit()
                logger.info(f"[EVENT_STARTED] Event ID {event.id} ('{event.title}') auto-transitioned to STARTED")

            alert_result = notify_hod_event_started(event)
            if alert_result:
                processed_alerts.append(alert_result)

    except Exception as e:
        logger.error(f"Error checking and notifying empty slots: {e}", exc_info=True)
        db.session.rollback()

    return processed_alerts


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
