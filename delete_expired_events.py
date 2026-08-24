"""
FastFest - Expired Events Cleanup Script
Deletes events whose end_time exceeds the current date/time ONLY IF all certificate
submissions/issuances for attendees are completed.
Usage:
    python delete_expired_events.py
"""

from datetime import datetime
from app import create_app
from services.event_service import delete_expired_events

def run_cleanup():
    app = create_app()
    with app.app_context():
        now = datetime.utcnow()
        print(f"[{now.strftime('%Y-%m-%d %H:%M:%S UTC')}] Scanning for expired events...")
        count, deleted_titles, skipped_titles = delete_expired_events(now, require_certificates_done=True)
        
        if count > 0:
            print(f"\nSuccessfully deleted {count} expired event(s) (all certificates were completed):")
            for t in deleted_titles:
                print(f" - {t}")
        else:
            print("\nNo eligible expired events deleted.")

        if skipped_titles:
            print(f"\nProtected {len(skipped_titles)} expired event(s) because certificate submission/issuance is NOT yet over:")
            for s in skipped_titles:
                print(f" - {s}")

        if count == 0 and not skipped_titles:
            print("All campus events are currently active or upcoming.")

if __name__ == '__main__':
    run_cleanup()
