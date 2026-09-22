"""
Campus Flow - Production Schema Migration Script
Safely applies missing columns to production PostgreSQL without dropping any tables
or losing existing user, event, registration, or payment data.
Specifically synchronizes and verifies:
  1. event_requests (registration_start_date, registration_deadline, etc.)
  2. events (registration_start_date, registration_type, etc.)
  3. payments (extracted_transaction_id, expected_amount, etc.)

Usage:
    python migrate_production_schema.py
"""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("CampusFlow.Migrate")

from app import create_app
from models import db, Payment, Event, EventRequest
from services.db_init import init_db_and_seed, sync_missing_columns
from services.db_diagnostic import get_safe_db_info
from sqlalchemy import inspect

def main():
    print("=" * 75)
    print("      CAMPUS FLOW - PRODUCTION DATABASE SCHEMA MIGRATION")
    print("=" * 75)

    app = create_app()
    with app.app_context():
        info = get_safe_db_info()
        print(f"Target Database Dialect : {info['dialect']}")
        print(f"Target Database Host    : {info['server']}")
        print(f"Target Database Name    : {info['database']}")
        print(f"Connected Status        : {info['connected']}")
        print("-" * 75)

        # 1. Attempt Alembic migrations via Flask-Migrate
        try:
            from flask_migrate import upgrade as flask_migrate_upgrade
            print("[*] Attempting Flask-Migrate database upgrade...")
            flask_migrate_upgrade()
            print("[+] Flask-Migrate upgrade applied successfully.")
        except Exception as mig_err:
            logger.warning(f"Flask-Migrate upgrade note (falling back to direct synchronization): {mig_err}")

        # 2. Run initialization and non-destructive column synchronization
        print("[*] Running schema inspection and non-destructive column synchronization...")
        init_db_and_seed(app, force=True)

        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())

        # 3. Verify 'event_requests' columns
        if 'event_requests' in existing_tables:
            er_cols = {c['name']: c['type'] for c in inspector.get_columns('event_requests')}
            print("\n[+] EVENT_REQUESTS TABLE VERIFICATION:")
            critical_er_cols = [
                'registration_start_date',
                'registration_deadline',
                'registration_fee',
                'is_free',
                'poster_image',
                'rules',
                'contact_info',
                'faculty_coordinator',
                'allowed_departments',
                'registration_type',
                'overall_status',
                'event_id'
            ]
            er_all_present = True
            for col in critical_er_cols:
                if col in er_cols:
                    print(f"  [OK] event_requests.{col} ({er_cols[col]})")
                else:
                    print(f"  [MISSING] event_requests.{col}")
                    er_all_present = False

            if not er_all_present:
                print("\n[ERROR] Missing required columns in event_requests!")
                sys.exit(1)
            else:
                print("  [SUCCESS] All critical event_requests columns verified.")

        # 4. Verify 'events' columns
        if 'events' in existing_tables:
            ev_cols = {c['name']: c['type'] for c in inspector.get_columns('events')}
            print("\n[+] EVENTS TABLE VERIFICATION:")
            critical_ev_cols = [
                'registration_start_date',
                'registration_deadline',
                'registration_type',
                'min_team_size',
                'max_team_size',
                'team_payment_type',
                'allowed_departments',
                'is_published',
                'hod_approved',
                'dean_approved'
            ]
            ev_all_present = True
            for col in critical_ev_cols:
                if col in ev_cols:
                    print(f"  [OK] events.{col} ({ev_cols[col]})")
                else:
                    print(f"  [MISSING] events.{col}")
                    ev_all_present = False

            if not ev_all_present:
                print("\n[ERROR] Missing required columns in events!")
                sys.exit(1)
            else:
                print("  [SUCCESS] All critical events columns verified.")

        # 5. Inspect 'payments' columns
        if 'payments' in existing_tables:
            pay_cols = {c['name']: c['type'] for c in inspector.get_columns('payments')}
            print("\n[+] PAYMENTS TABLE VERIFICATION:")
            critical_pay_cols = [
                'extracted_transaction_id',
                'expected_amount',
                'detected_amount',
                'screenshot_hash',
                'fraud_risk',
                'ocr_extracted_data',
                'verification_reason',
                'submitted_at',
                'verified_at',
                'team_id'
            ]
            pay_all_present = True
            for col in critical_pay_cols:
                if col in pay_cols:
                    print(f"  [OK] payments.{col} ({pay_cols[col]})")
                else:
                    print(f"  [MISSING] payments.{col}")
                    pay_all_present = False

            if not pay_all_present:
                print("\n[WARNING] Some payment columns are still missing!")
                sys.exit(1)
            else:
                print("  [SUCCESS] All critical payment verification columns verified.")

        # 6. Test Model Queries Directly
        print("\n[+] TESTING MODEL QUERY EXECUTION:")
        try:
            er_count = EventRequest.query.count()
            print(f"  [OK] EventRequest.query.count() = {er_count}")
        except Exception as e:
            print(f"  [ERROR] EventRequest query failed: {e}")
            sys.exit(1)

        try:
            ev_count = Event.query.count()
            print(f"  [OK] Event.query.count() = {ev_count}")
        except Exception as e:
            print(f"  [ERROR] Event query failed: {e}")
            sys.exit(1)

        try:
            pay_count = Payment.query.count()
            print(f"  [OK] Payment.query.count() = {pay_count}")
        except Exception as e:
            print(f"  [ERROR] Payment query failed: {e}")
            sys.exit(1)

        print("\n" + "=" * 75)
        print("MIGRATION COMPLETED SUCCESSFULLY. PRODUCTION SCHEMA IS FULLY SYNCHRONIZED.")
        print("=" * 75)

if __name__ == '__main__':
    main()
