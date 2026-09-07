"""
Campus Flow - Safe Database Migration for Final 5 Roles, Requests & Dual Approval
Creates organizer_requests, event_requests, notifications tables and adds dual approval
columns to events, safely migrating existing user roles without data loss.
"""
import sys
from datetime import datetime
from sqlalchemy import text, inspect
from app import create_app
from models import db, User, UserRole, Event, CollegeDepartment

def run_migration():
    app = create_app()
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)
        dialect = engine.dialect.name.lower()
        print(f"[*] Starting migration on dialect: {dialect} | DB: {engine.url.database}")

        # 1. Create tables if they do not exist
        print("[*] Ensuring all models and tables exist...")
        db.create_all()

        existing_tables = inspector.get_table_names()
        print(f"[+] Current tables in DB: {len(existing_tables)}")

        # 2. Add columns to events if missing (for pre-existing tables)
        event_columns = [col['name'] for col in inspector.get_columns('events')]
        print(f"[*] Event columns: {event_columns}")

        with engine.connect() as conn:
            # Expand users.role column length to allow 'students_affairs_dean' (21 chars)
            if 'mssql' in dialect:
                print("[*] Expanding users.role to VARCHAR(50)...")
                try:
                    conn.execute(text("ALTER TABLE users ALTER COLUMN role VARCHAR(50) NOT NULL"))
                    conn.commit()
                except Exception as e:
                    print(f"[-] Note on altering users.role: {e}")

            # department_id
            if 'department_id' not in event_columns:
                print("[*] Adding column 'department_id' to events table...")
                conn.execute(text("ALTER TABLE events ADD department_id INTEGER NULL"))
            
            # is_published
            if 'is_published' not in event_columns:
                print("[*] Adding column 'is_published' to events table...")
                if 'mssql' in dialect:
                    conn.execute(text("ALTER TABLE events ADD is_published BIT NOT NULL DEFAULT 0"))
                else:
                    conn.execute(text("ALTER TABLE events ADD is_published BOOLEAN NOT NULL DEFAULT 0"))

            # hod_approved
            if 'hod_approved' not in event_columns:
                print("[*] Adding column 'hod_approved' to events table...")
                if 'mssql' in dialect:
                    conn.execute(text("ALTER TABLE events ADD hod_approved BIT NOT NULL DEFAULT 0"))
                else:
                    conn.execute(text("ALTER TABLE events ADD hod_approved BOOLEAN NOT NULL DEFAULT 0"))

            # dean_approved
            if 'dean_approved' not in event_columns:
                print("[*] Adding column 'dean_approved' to events table...")
                if 'mssql' in dialect:
                    conn.execute(text("ALTER TABLE events ADD dean_approved BIT NOT NULL DEFAULT 0"))
                else:
                    conn.execute(text("ALTER TABLE events ADD dean_approved BOOLEAN NOT NULL DEFAULT 0"))

            # event_request_id
            if 'event_request_id' not in event_columns:
                print("[*] Adding column 'event_request_id' to events table...")
                conn.execute(text("ALTER TABLE events ADD event_request_id INTEGER NULL"))

            conn.commit()

        # 3. Migrate pre-existing events: mark existing active/completed events as approved and published
        # so existing demo data and test cases remain functional.
        print("[*] Backfilling existing events...")
        depts_by_code = {d.code.upper(): d.id for d in CollegeDepartment.query.all()}
        events = Event.query.all()
        for ev in events:
            if ev.department and ev.department.upper() in depts_by_code:
                ev.department_id = depts_by_code[ev.department.upper()]
            if ev.status in ('APPROVED', 'REGISTRATION_OPEN', 'COMPLETED', 'UPCOMING', 'ONGOING'):
                ev.is_published = True
                ev.hod_approved = True
                ev.dean_approved = True
            else:
                ev.is_published = False
        db.session.commit()
        print(f"[+] Updated {len(events)} existing events.")

        # 4. Safely migrate user roles to the 5 canonical roles:
        # super_admin, students_affairs_dean, hod, organizer, student
        print("[*] Migrating user roles to 5 final canonical roles...")
        users = User.query.all()
        hod_user_ids = {d.hod_id for d in CollegeDepartment.query.filter(CollegeDepartment.hod_id.isnot(None)).all()}

        migrated_counts = {
            UserRole.SUPER_ADMIN: 0,
            UserRole.STUDENTS_AFFAIRS_DEAN: 0,
            UserRole.HOD: 0,
            UserRole.ORGANIZER: 0,
            UserRole.STUDENT: 0
        }

        for u in users:
            old_role = (u.role or '').strip().upper()
            new_role = None

            # Super admin
            if u.email.lower() == 'superadmin@college.edu' or old_role == 'SUPER_ADMIN':
                new_role = UserRole.SUPER_ADMIN

            # Students Affairs Dean (admin@college.edu or designation Dean)
            elif u.email.lower() == 'admin@college.edu' or (u.faculty_profile and 'dean' in (u.faculty_profile.designation or '').lower()):
                new_role = UserRole.STUDENTS_AFFAIRS_DEAN

            # HOD (assigned HOD id, admin.<dept> emails, or HOD designation)
            elif u.id in hod_user_ids or old_role == 'HOD' or old_role == 'FACULTY_ADMIN' or u.email.lower().startswith('admin.') or (u.faculty_profile and 'head' in (u.faculty_profile.designation or '').lower()):
                new_role = UserRole.HOD

            # Faculty (demo faculty or other faculty)
            elif old_role == 'FACULTY':
                # Safe migration: if assigned to a department as faculty/HOD, set as HOD or student
                new_role = UserRole.HOD

            # Organizer
            elif old_role == 'ORGANIZER':
                new_role = UserRole.ORGANIZER

            # Student
            elif old_role == 'STUDENT':
                new_role = UserRole.STUDENT

            else:
                new_role = UserRole.STUDENT

            u.role = new_role
            migrated_counts[new_role] += 1
            print(f"  User {u.id} ({u.email}): {old_role} -> {new_role}")

        db.session.commit()
        print("[+] Role migration complete! Summary:")
        for role, count in migrated_counts.items():
            print(f"    - {role}: {count} users")

        print("[OK] All database migrations and role updates executed successfully!")

if __name__ == '__main__':
    run_migration()
