import os
import shutil
from datetime import datetime
from pathlib import Path
from flask import current_app
from models import db, Event, EventRegistration, Certificate, AttendanceRecord

def _delete_file_safely(relative_path):
    """Safely removes a file from static folder if it exists."""
    if not relative_path:
        return
    try:
        base_dir = Path(__file__).resolve().parent.parent / 'static'
        file_path = base_dir / relative_path
        if file_path.exists() and file_path.is_file():
            file_path.unlink(missing_ok=True)
    except Exception:
        pass


def are_certificates_completed(event):
    """
    Checks if certificate submission/issuance is fully completed for the event.
    Returns False if there are verified attendees who have not yet received certificates.
    """
    attended_regs = [r for r in event.registrations if r.attendance is not None]
    if not attended_regs:
        return True
    
    # All attended participants must have certificates generated
    return all(r.certificate is not None for r in attended_regs)


def delete_event_with_cleanup(event):
    """
    Deletes an event and all associated generated files (posters, QR codes, certificates),
    relying on database cascade deletion for child models.
    """
    # 1. Clean up poster image
    if event.poster_image:
        _delete_file_safely(event.poster_image)

    # 2. Clean up registration QR codes
    for reg in event.registrations:
        if reg.qr_code_image:
            _delete_file_safely(reg.qr_code_image)

    # 3. Clean up all uploaded event certificates
    for cert in event.certificates:
        if cert.file_path:
            _delete_file_safely(cert.file_path)

    # Remove event certificate folder if empty
    try:
        cert_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'certificates' / f"event_{event.id}"
        if cert_dir.exists() and cert_dir.is_dir():
            shutil.rmtree(cert_dir, ignore_errors=True)
    except Exception:
        pass

    # 4. Delete event entity from database
    db.session.delete(event)


def delete_expired_events(cutoff_datetime=None, require_certificates_done=True):
    """
    Deletes all events whose end_time is earlier than the cutoff_datetime.
    If require_certificates_done is True, will NOT delete events where
    attendees are still pending certificate issuance.
    
    Returns (deleted_count, list_of_deleted_event_titles, list_of_skipped_event_titles).
    """
    if cutoff_datetime is None:
        cutoff_datetime = datetime.utcnow()

    # Query events that exceed the date (end_time < cutoff_datetime)
    expired_events = Event.query.filter(Event.end_time < cutoff_datetime).all()

    if not expired_events:
        return 0, [], []

    deleted_titles = []
    skipped_titles = []

    for ev in expired_events:
        # Check certificate completion rule
        if require_certificates_done and not are_certificates_completed(ev):
            attended_count = len([r for r in ev.registrations if r.attendance is not None])
            issued_count = len([r for r in ev.registrations if r.attendance is not None and r.certificate is not None])
            skipped_titles.append(
                f"{ev.title} (ID: {ev.id}, Pending Certs: {attended_count - issued_count}/{attended_count})"
            )
            continue

        deleted_titles.append(f"{ev.title} (ID: {ev.id}, Ended: {ev.end_time.strftime('%Y-%m-%d %H:%M')})")
        delete_event_with_cleanup(ev)

    db.session.commit()
    return len(deleted_titles), deleted_titles, skipped_titles
