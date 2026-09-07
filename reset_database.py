"""
Campus Flow - Production Database Reset Utility

WARNING: This script permanently clears all existing application data:
- Students, Organizers, Users
- Events, Registrations, Custom Form Responses
- Attendance Records, Payments, Announcements
- Certificates and uploaded media artifacts

It keeps all tables, schemas, relationships, constraints, and indexes intact.
This script is NEVER run automatically.

Usage:
  python reset_database.py            # Interactive with confirmation prompt
  python reset_database.py --confirm  # Automated confirmation for deployment
"""

import sys
import shutil
from pathlib import Path
from app import create_app
from models import db
from backup_database import backup_database

BASE_DIR = Path(__file__).resolve().parent

def clean_upload_directories():
    """Removes all uploaded files while preserving the directory structure."""
    upload_dirs = [
        BASE_DIR / 'static' / 'uploads' / 'posters',
        BASE_DIR / 'static' / 'uploads' / 'qrcodes',
        BASE_DIR / 'static' / 'uploads' / 'certificates'
    ]
    for d in upload_dirs:
        if d.exists():
            for item in d.iterdir():
                if item.is_file():
                    try:
                        item.unlink()
                    except Exception:
                        pass
                elif item.is_dir():
                    try:
                        shutil.rmtree(item, ignore_errors=True)
                    except Exception:
                        pass
        else:
            d.mkdir(parents=True, exist_ok=True)
    print("Upload directories cleaned successfully.")


def reset_database(force=False):
    print("=" * 60)
    print("             CAMPUS FLOW - DATABASE RESET UTILITY")
    print("=" * 60)
    print("WARNING: This will permanently delete ALL application data:")
    print("  - All student, organizer, and demo accounts")
    print("  - All events, registrations, tickets, payments, attendance")
    print("  - All certificates and uploaded artifacts")
    print("=" * 60)

    if not force:
        confirmation = input("Type 'RESET' in capital letters to confirm: ").strip()
        if confirmation != 'RESET':
            print("Operation aborted. No changes made.")
            return False

    print("\n[1/3] Creating automatic pre-reset backup...")
    try:
        backup_path = backup_database()
        print(f"Backup created: {backup_path}")
    except Exception as e:
        print(f"Backup notice: {e}")

    print("\n[2/3] Re-initializing database tables...")
    app = create_app()
    with app.app_context():
        try:
            # Recreate all tables cleanly
            db.drop_all()
            db.create_all()
            print("Database tables recreated successfully with full schema and constraints.")
        except Exception as e:
            print(f"Error resetting database tables: {e}")
            raise e

    print("\n[3/3] Cleaning uploaded demo artifacts...")
    clean_upload_directories()

    print("\n" + "=" * 60)
    print(" DATABASE RESET COMPLETE: Clean Production Database Ready!")
    print("=" * 60)
    print("Next step: Create your production administrator account by running:")
    print("  python create_admin.py")
    print("=" * 60 + "\n")
    return True


if __name__ == '__main__':
    force_flag = '--confirm' in sys.argv or '-y' in sys.argv
    reset_database(force=force_flag)
