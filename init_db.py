"""
Campus Flow - Database Initialization & Baseline Seeding CLI Script

Usage:
    python init_db.py

Can be executed directly, configured as a Render Pre-Deploy Command:
    python init_db.py
or appended to the Render Build Command:
    pip install -r requirements.txt && python init_db.py
"""

import os
import sys
import logging

# Ensure basic stdout logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

from app import create_app
from services.db_init import init_db_and_seed
from services.db_diagnostic import get_safe_db_info

def main():
    print("=" * 70)
    print("      CAMPUS FLOW - RENDER POSTGRESQL DATABASE INITIALIZER")
    print("=" * 70)
    
    app = create_app()
    with app.app_context():
        # Display safe diagnostic info before running
        info = get_safe_db_info()
        print(f"Target Database Dialect : {info['dialect']}")
        print(f"Target Database Host    : {info['server']}")
        print(f"Target Database Name    : {info['database']}")
        print(f"Connected               : {info['connected']}")
        print("-" * 70)

        success = init_db_and_seed(app)
        if success:
            print("\n[SUCCESS] All 21 tables verified and baseline administrative users provisioned.")
            print("You can now log in at /auth/login with:")
            admin_email = os.environ.get('SUPER_ADMIN_EMAIL', 'superadmin@college.edu')
            print(f"  Super Admin Email : {admin_email}")
            print(f"  Role              : super_admin (SUPER_ADMIN)")
            print("=" * 70)
            sys.exit(0)
        else:
            print("\n[FAILURE] Database initialization encountered an error.")
            sys.exit(1)

if __name__ == '__main__':
    main()
