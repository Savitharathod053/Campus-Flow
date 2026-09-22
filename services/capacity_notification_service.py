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

    from services.timezone_service import format_ist_datetime
    start_time_ist = format_ist_datetime(event.start_time) if event.start_time else "N/A"
    organizer_name = event.organizer.name if event.organizer else "Event Organizer"
    dept_display = event.department or (event.department_rel.name if event.department_rel else "Department")

    # 1. Create In-App Notification
    notification_title = f"🔔 Event Started (Event Capacity Alert): {event.title}"
    notification_message = (
        f"Event \"{event.title}\" (ID: #{event.id}) in {dept_display} has started and currently has {empty_slots} empty slots out of {total_capacity} ({empty_slots} empty slots remaining).\n"
        f"Department: {dept_display} | Organizer: {organizer_name} | "
        f"Confirmed Students: {confirmed_count} | Empty Slots: {empty_slots} | "
        f"Event Start Time: {start_time_ist}"
    )

    now = datetime.utcnow()
    in_app_notif = Notification(
        user_id=hod.id,
        title=notification_title,
        message=notification_message,
        type=NotificationType.EVENT_CAPACITY_ALERT,
        link=f"/events/{event.id}",
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
    logger.info(f"[HOD_NOTIFICATION_CREATED] In-app notification #{in_app_notif.id} created for HOD {hod.email} (User ID: {hod.id})")

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


def check_and_notify_empty_slots(app=None):
    """
    Scans events that have reached their start time (start_time <= now) or are active/started.
    - Transitions their lifecycle status to STARTED if appropriate.
    - If unfilled slots remain (empty_slots > 0), sends an in-app notification
      and an email to the responsible HOD.
    - Prevents duplicate alerts via event.empty_slot_notification_sent flag
      and EventNotificationLog records.
    Returns:
        list: Summary of processed event notifications
    """
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
    Launches a daemon background thread that periodically inspects starting events
    and triggers empty slot notifications to responsible HODs.
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
                        check_and_notify_empty_slots(app)
                except Exception as worker_err:
                    logger.error(f"Error in capacity monitoring scheduler loop: {worker_err}", exc_info=True)
                time.sleep(interval_seconds)

        thread = threading.Thread(target=_worker, name="CapacityMonitoringScheduler", daemon=True)
        thread.start()
        _SCHEDULER_STARTED = True
        logger.info("Capacity monitoring scheduler background thread launched.")
