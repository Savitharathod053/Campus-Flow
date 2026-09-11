"""
Database Migration Script for Campus Flow: Add roll_number to organizer_profiles.
Supports Microsoft SQL Server / SSMS, PostgreSQL, and SQLite.
"""
from app import create_app
from models import db
from sqlalchemy import inspect, text


def run_migration():
    app = create_app()
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)
        dialect = engine.dialect.name.lower()
        print(f"[*] Checking 'organizer_profiles' table on database dialect: {dialect}...")

        # Ensure all models and tables exist
        db.create_all()

        existing_tables = inspector.get_table_names()
        if 'organizer_profiles' not in existing_tables:
            print("[-] 'organizer_profiles' table not found.")
            return

        columns = [c['name'] for c in inspector.get_columns('organizer_profiles')]
        if 'roll_number' not in columns:
            print("[*] Adding 'roll_number' column to 'organizer_profiles'...")
            with engine.connect() as conn:
                # PostgreSQL supports ADD COLUMN roll_number VARCHAR(50) UNIQUE
                # MSSQL (T-SQL) requires ADD roll_number VARCHAR(50) UNIQUE (keyword 'COLUMN' is invalid syntax in MSSQL)
                if 'postgres' in dialect:
                    conn.execute(text("ALTER TABLE organizer_profiles ADD COLUMN roll_number VARCHAR(50) UNIQUE"))
                elif 'mssql' in dialect:
                    conn.execute(text("ALTER TABLE organizer_profiles ADD roll_number VARCHAR(50) UNIQUE"))
                else:
                    # SQLite or general fallback
                    try:
                        conn.execute(text("ALTER TABLE organizer_profiles ADD COLUMN roll_number VARCHAR(50) UNIQUE"))
                    except Exception:
                        conn.execute(text("ALTER TABLE organizer_profiles ADD roll_number VARCHAR(50)"))
                conn.commit()
            print("[+] 'roll_number' column added to 'organizer_profiles'.")
        else:
            print("[+] 'roll_number' column already exists in 'organizer_profiles'.")

        # Backfill existing demo organizer if present and roll_number is NULL
        with engine.connect() as conn:
            try:
                conn.execute(text(
                    "UPDATE organizer_profiles SET roll_number = 'DEMO2026ORG001' "
                    "WHERE roll_number IS NULL AND user_id IN (SELECT id FROM users WHERE email = 'organizer.demo@college.edu')"
                ))
                conn.commit()
                print("[+] Verified demo organizer roll_number backfill.")
            except Exception as e:
                print(f"[-] Note on demo organizer backfill: {e}")

        print("[+] Migration completed successfully!")


if __name__ == '__main__':
    run_migration()
