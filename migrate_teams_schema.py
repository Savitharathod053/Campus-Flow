"""
Database Migration Script for Campus Flow Team / Group Registration Schema.
Supports Microsoft SQL Server / SSMS, SQLite, and MySQL.
"""
from app import create_app
from models import db
from sqlalchemy import inspect, text

def run_teams_migration():
    app = create_app()
    with app.app_context():
        engine = db.engine
        inspector = inspect(engine)
        dialect = engine.dialect.name
        print(f"Running migration on database dialect: {dialect}...")

        # 1. Ensure new tables (teams, team_members, team_invitations) exist
        db.create_all()
        print("db.create_all() executed to create any missing tables.")

        # 2. Check and add missing columns on existing tables
        existing_tables = inspector.get_table_names()

        # Events table columns
        if 'events' in existing_tables:
            event_cols = [c['name'] for c in inspector.get_columns('events')]
            with engine.connect() as conn:
                if 'registration_type' not in event_cols:
                    print("Adding 'registration_type' to events...")
                    conn.execute(text("ALTER TABLE events ADD registration_type VARCHAR(20) DEFAULT 'INDIVIDUAL' NOT NULL"))
                if 'min_team_size' not in event_cols:
                    print("Adding 'min_team_size' to events...")
                    conn.execute(text("ALTER TABLE events ADD min_team_size INT DEFAULT 2 NOT NULL"))
                if 'max_team_size' not in event_cols:
                    print("Adding 'max_team_size' to events...")
                    conn.execute(text("ALTER TABLE events ADD max_team_size INT DEFAULT 4 NOT NULL"))
                if 'team_payment_type' not in event_cols:
                    print("Adding 'team_payment_type' to events...")
                    conn.execute(text("ALTER TABLE events ADD team_payment_type VARCHAR(20) DEFAULT 'FREE' NOT NULL"))
                if 'require_full_team' not in event_cols:
                    print("Adding 'require_full_team' to events...")
                    if dialect == 'mssql':
                        conn.execute(text("ALTER TABLE events ADD require_full_team BIT DEFAULT 0 NOT NULL"))
                    elif dialect == 'sqlite':
                        conn.execute(text("ALTER TABLE events ADD require_full_team BOOLEAN DEFAULT 0 NOT NULL"))
                    else:
                        conn.execute(text("ALTER TABLE events ADD require_full_team BOOLEAN DEFAULT FALSE NOT NULL"))
                conn.commit()

        # Event Registrations table columns
        if 'event_registrations' in existing_tables:
            reg_cols = [c['name'] for c in inspector.get_columns('event_registrations')]
            with engine.connect() as conn:
                if 'team_id' not in reg_cols:
                    print("Adding 'team_id' to event_registrations...")
                    conn.execute(text("ALTER TABLE event_registrations ADD team_id INT NULL"))
                conn.commit()

        # Payments table columns
        if 'payments' in existing_tables:
            pay_cols = [c['name'] for c in inspector.get_columns('payments')]
            with engine.connect() as conn:
                if 'team_id' not in pay_cols:
                    print("Adding 'team_id' to payments...")
                    conn.execute(text("ALTER TABLE payments ADD team_id INT NULL"))
                conn.commit()

        print("Migration for Team Registration completed successfully!")

if __name__ == '__main__':
    run_teams_migration()
