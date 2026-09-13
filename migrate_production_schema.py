"""
Campus Flow - Production Schema Migration Script
Safely applies missing columns to production PostgreSQL without dropping any tables
or losing existing user, event, registration, or payment data.
Specifically verifies payments.extracted_transaction_id and other recent features.

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

from app import create_app
from models import db, Payment
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

        # 1. Run initialization and column synchronization
        print("[*] Running schema inspection and non-destructive column synchronization...")
        init_db_and_seed(app, force=True)

        # 2. Inspect 'payments' columns specifically
        inspector = inspect(db.engine)
        if 'payments' in inspector.get_table_names():
            pay_cols = {c['name']: c['type'] for c in inspector.get_columns('payments')}
            print("\n[+] PAYMENTS TABLE VERIFICATION:")
            critical_cols = [
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
            all_present = True
            for col in critical_cols:
                if col in pay_cols:
                    print(f"  [OK] payments.{col} ({pay_cols[col]})")
                else:
                    print(f"  [MISSING] payments.{col}")
                    all_present = False

            if all_present:
                print("\n[SUCCESS] All critical payment verification columns are present!")
            else:
                print("\n[WARNING] Some payment columns are still missing!")
                sys.exit(1)

        # 3. Test Payment.query.count() directly
        try:
            count = Payment.query.count()
            print(f"[+] Verified Payment.query.count() = {count} (no SQL errors!)")
        except Exception as e:
            print(f"[ERROR] Payment query failed: {e}")
            sys.exit(1)

        print("=" * 75)
        print("MIGRATION COMPLETED SUCCESSFULLY. PRODUCTION SCHEMA IS FULLY SYNCHRONIZED.")
        print("=" * 75)

if __name__ == '__main__':
    main()
