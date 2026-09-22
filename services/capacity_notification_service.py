"""
Campus Flow - Automatic Empty Slots Capacity Notification Service
Monitors events as they reach their start time and notifies the responsible HOD
if unfilled/empty registration slots exist.
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


def check_and_notify_empty_slots(app=None):
    """
    Scans events that have reached their start time (start_time <= now) and are active.
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
        # Fetch events that have reached or passed their start time
        # and are not already completed/cancelled/rejected
        events = Event.query.filter(
            Event.start_time <= now,
            Event.status.notin_([
                EventStatus.COMPLETED,
                'EVENT_COMPLETED',
                EventStatus.CANCELLED,
                EventStatus.REJECTED,
                EventStatus.DRAFT
            ])
        ).all()

        for event in events:
            # Check dual approval / publishing
            if not event.is_published_and_approved:
                continue

            # Automatically transition status to STARTED if currently UPCOMING or APPROVED or REGISTRATION_OPEN
            if event.status in (EventStatus.UPCOMING, EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN):
                event.status = EventStatus.STARTED
                db.session.add(event)

            # Check if notification was already dispatched for this event
            if event.empty_slot_notification_sent:
                continue

            total_capacity = event.max_participants or 0
            confirmed_count = event.confirmed_registrations_count
            empty_slots = max(0, total_capacity - confirmed_count)

            # If no empty slots (fully booked), do not send notification
            if empty_slots <= 0:
                event.empty_slot_notification_sent = True
                db.session.add(event)
                continue

            # Resolve the responsible HOD
            hod = event.get_responsible_hod()
            if not hod:
                logger.warning(
                    f"Event ID {event.id} ('{event.title}') has {empty_slots} empty slots, "
                    f"but no responsible HOD could be resolved for department '{event.department}'."
                )
                # Mark as processed to prevent infinite retry log noise, or leave for when HOD is assigned?
                # We mark as notified so we don't spam errors every minute
                event.empty_slot_notification_sent = True
                db.session.add(event)
                continue

            # Enforce duplicate check in EventNotificationLog
            existing_log = EventNotificationLog.query.filter_by(
                event_id=event.id,
                notification_type=NotificationType.EVENT_CAPACITY_ALERT,
                recipient_user_id=hod.id
            ).first()

            if existing_log:
                logger.info(f"Capacity alert already logged for Event {event.id} and HOD {hod.id}. Skipping.")
                event.empty_slot_notification_sent = True
                db.session.add(event)
                continue

            # 1. Create In-App Notification
            notification_title = f"🔔 Event Capacity Alert: {event.title}"
            notification_message = f"{event.title} has started and currently has {empty_slots} empty slots out of {total_capacity}."
            
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

            # 2. Log in EventNotificationLog for strict audit and duplicate prevention
            log_entry = EventNotificationLog(
                event_id=event.id,
                notification_type=NotificationType.EVENT_CAPACITY_ALERT,
                recipient_user_id=hod.id,
                sent_at=now,
                status='SENT',
                details=f"Empty slots: {empty_slots}/{total_capacity} (Confirmed: {confirmed_count})"
            )
            db.session.add(log_entry)

            # 3. Mark event flag as sent
            event.empty_slot_notification_sent = True
            db.session.add(event)

            # Commit changes to database
            db.session.commit()

            # 4. Dispatch Email to HOD
            email_dispatched = False
            try:
                email_dispatched = send_empty_slots_hod_email(
                    hod=hod,
                    event=event,
                    empty_slots=empty_slots,
                    total_capacity=total_capacity,
                    confirmed_count=confirmed_count
                )
            except Exception as mail_err:
                logger.error(f"Failed to send empty slots email to HOD {hod.email}: {mail_err}", exc_info=True)

            logger.info(
                f"[CAPACITY ALERT] Successfully alerted HOD {hod.email} for event '{event.title}' "
                f"({empty_slots}/{total_capacity} empty slots). In-app created: Yes, Email sent: {email_dispatched}."
            )

            processed_alerts.append({
                'event_id': event.id,
                'event_title': event.title,
                'hod_id': hod.id,
                'hod_email': hod.email,
                'empty_slots': empty_slots,
                'total_capacity': total_capacity,
                'confirmed_students': confirmed_count,
                'email_sent': email_dispatched
            })

        db.session.commit()

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
