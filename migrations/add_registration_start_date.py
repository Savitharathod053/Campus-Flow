import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app, db
from sqlalchemy import text

def run_migration():
    with app.app_context():
        # Check events table
        cols = [r[0] for r in db.session.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='events'")).fetchall()]
        if 'registration_start_date' not in cols:
            db.session.execute(text("ALTER TABLE events ADD registration_start_date DATETIME NULL;"))
            print("Added registration_start_date to events")
        else:
            print("registration_start_date already exists in events")

        # Check event_requests table
        req_cols = [r[0] for r in db.session.execute(text("SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='event_requests'")).fetchall()]
        if 'registration_start_date' not in req_cols:
            db.session.execute(text("ALTER TABLE event_requests ADD registration_start_date DATETIME NULL;"))
            print("Added registration_start_date to event_requests")
        else:
            print("registration_start_date already exists in event_requests")

        # Backfill with created_at where NULL
        db.session.execute(text("UPDATE events SET registration_start_date = created_at WHERE registration_start_date IS NULL;"))
        db.session.execute(text("UPDATE event_requests SET registration_start_date = created_at WHERE registration_start_date IS NULL;"))
        db.session.commit()
        print("Backfill complete and committed successfully.")

if __name__ == '__main__':
    run_migration()
