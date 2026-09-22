"""
Campus Flow - Database Initialization & Baseline Seeding Service
Ensures that all tables exist and baseline institutional administrative
records (Super Admin, Departments, Dean, HOD) are safely provisioned.
This service is completely idempotent: it never drops or overwrites existing data.
"""

import os
import logging
from models import (
    db, User, UserRole, FacultyProfile, StudentProfile,
    OrganizerProfile, CollegeDepartment, Department
)

logger = logging.getLogger("CampusFlow.DBInit")
_DB_INITIALIZED = False


def ensure_db_initialized(app):
    """
    Guarantees database schema tables exist before serving any request.
    If already initialized, returns immediately in sub-millisecond time.
    """
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return True
    return init_db_and_seed(app)


def init_db_and_seed(app, force=False):
    """
    Initializes all database tables, ensures all model columns exist on pre-existing tables,
    and seeds the essential baseline. Returns True on success, False on failure.
    """
    global _DB_INITIALIZED
    if _DB_INITIALIZED and not force:
        return True

    with app.app_context():
        try:
            # 1. Create all 21 tables idempotently
            logger.info("Verifying and creating database tables via SQLAlchemy metadata...")
            db.create_all()
            logger.info("Database schema tables verified.")

            # 2. Synchronize any missing columns on pre-existing tables (e.g. payments.extracted_transaction_id)
            sync_missing_columns()

            # 3. Seed canonical college departments if empty
            _seed_departments()

            # 4. Seed initial Super Admin if not present
            _seed_super_admin()

            # 5. Seed baseline Dean and HOD accounts if missing
            _seed_baseline_officials()

            db.session.commit()
            _DB_INITIALIZED = True
            logger.info("Database initialization, schema synchronization, and seeding completed successfully.")
            return True
        except Exception as e:
            logger.error(f"Database initialization encountered an error: {e}", exc_info=True)
            db.session.rollback()
            return False


def sync_missing_columns():
    """
    Safely inspects existing tables and non-destructively adds any missing columns.
    Ensures that newly added model columns (such as payments.extracted_transaction_id)
    exist in the production database without dropping or altering existing records.
    """
    engine = db.engine
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    dialect = engine.dialect.name.lower()
    existing_tables = set(inspector.get_table_names())

    specs = {
        'payments': [
            ('extracted_transaction_id', 'VARCHAR(100)', None, True),
            ('expected_amount', 'FLOAT', None, True),
            ('detected_amount', 'FLOAT', None, True),
            ('screenshot_hash', 'VARCHAR(64)', None, True),
            ('fraud_risk', 'VARCHAR(20)', "'LOW'", True),
            ('fraud_details', 'TEXT', None, True),
            ('ocr_extracted_data', 'TEXT', None, True),
            ('verification_reason', 'TEXT', None, True),
            ('notes', 'TEXT', None, True),
            ('submitted_at', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
            ('verified_at', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
            ('verified_by_id', 'INTEGER', None, True),
            ('team_id', 'INTEGER', None, True),
            ('event_id', 'INTEGER', None, True),
            ('student_id', 'INTEGER', None, True),
            ('organizer_id', 'INTEGER', None, True),
            ('razorpay_order_id', 'VARCHAR(100)', None, True),
            ('razorpay_payment_id', 'VARCHAR(100)', None, True),
            ('razorpay_signature', 'VARCHAR(255)', None, True),
            ('webhook_event_id', 'VARCHAR(100)', None, True),
            ('failure_reason', 'TEXT', None, True),
            ('razorpay_status', 'VARCHAR(50)', None, True),
        ],
        'events': [
            ('registration_start_date', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
            ('registration_type', 'VARCHAR(20)', "'INDIVIDUAL'", False),
            ('min_team_size', 'INTEGER', '2', False),
            ('max_team_size', 'INTEGER', '4', False),
            ('team_payment_type', 'VARCHAR(20)', "'FREE'", False),
            ('require_full_team', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'FALSE' if 'postgres' in dialect else '0', False),
            ('upi_id', 'VARCHAR(100)', None, True),
            ('upi_number', 'VARCHAR(20)', None, True),
            ('upi_qr_image', 'VARCHAR(255)', None, True),
            ('payment_instructions', 'TEXT', None, True),
            ('enable_attendance', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'TRUE' if 'postgres' in dialect else '1', False),
            ('min_attendance_percentage', 'FLOAT', '0.0', False),
            ('department_id', 'INTEGER', None, True),
            ('is_published', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'FALSE' if 'postgres' in dialect else '0', False),
            ('hod_approved', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'FALSE' if 'postgres' in dialect else '0', False),
            ('dean_approved', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'FALSE' if 'postgres' in dialect else '0', False),
            ('event_request_id', 'INTEGER', None, True),
            ('rejection_reason', 'TEXT', None, True),
            ('allowed_departments', 'VARCHAR(255)', "'ALL'", False),
            ('allowed_years', 'VARCHAR(50)', "'ALL'", False),
            ('allowed_sections', 'VARCHAR(50)', "'ALL'", False),
            ('eligibility_notes', 'VARCHAR(255)', None, True),
            ('empty_slot_notification_sent', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'FALSE' if 'postgres' in dialect else '0', False),
            ('responsible_hod_id', 'INTEGER', None, True),
        ],
        'event_requests': [
            ('registration_start_date', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
            ('registration_deadline', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
            ('registration_fee', 'FLOAT', '0.0', False),
            ('is_free', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'TRUE' if 'postgres' in dialect else '1', False),
            ('poster_image', 'VARCHAR(255)', None, True),
            ('rules', 'TEXT', None, True),
            ('contact_info', 'VARCHAR(200)', None, True),
            ('faculty_coordinator', 'VARCHAR(150)', None, True),
            ('faculty_coordinator_contact', 'VARCHAR(100)', None, True),
            ('allowed_departments', 'VARCHAR(255)', "'ALL'", False),
            ('allowed_years', 'VARCHAR(50)', "'ALL'", False),
            ('allowed_sections', 'VARCHAR(50)', "'ALL'", False),
            ('eligibility_notes', 'VARCHAR(255)', None, True),
            ('registration_type', 'VARCHAR(20)', "'INDIVIDUAL'", False),
            ('min_team_size', 'INTEGER', '2', False),
            ('max_team_size', 'INTEGER', '4', False),
            ('team_payment_type', 'VARCHAR(20)', "'FREE'", False),
            ('require_full_team', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'FALSE' if 'postgres' in dialect else '0', False),
            ('upi_id', 'VARCHAR(100)', None, True),
            ('upi_number', 'VARCHAR(20)', None, True),
            ('upi_qr_image', 'VARCHAR(255)', None, True),
            ('payment_instructions', 'TEXT', None, True),
            ('enable_attendance', 'BOOLEAN' if 'postgres' in dialect else ('BIT' if 'mssql' in dialect else 'BOOLEAN'), 'TRUE' if 'postgres' in dialect else '1', False),
            ('min_attendance_percentage', 'FLOAT', '0.0', False),
            ('hod_reviewer_id', 'INTEGER', None, True),
            ('hod_approval_status', 'VARCHAR(30)', "'pending'", False),
            ('hod_decision_at', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
            ('hod_rejection_reason', 'TEXT', None, True),
            ('dean_reviewer_id', 'INTEGER', None, True),
            ('dean_approval_status', 'VARCHAR(30)', "'pending'", False),
            ('dean_decision_at', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
            ('dean_rejection_reason', 'TEXT', None, True),
            ('overall_status', 'VARCHAR(30)', "'pending_hod_approval'", False),
            ('event_id', 'INTEGER', None, True),
        ],
        'organizer_profiles': [
            ('roll_number', 'VARCHAR(50)', None, True),
            ('rejection_reason', 'VARCHAR(255)', None, True),
            ('approved_by_id', 'INTEGER', None, True),
            ('approved_at', 'TIMESTAMP' if 'postgres' in dialect else 'DATETIME', None, True),
        ],
        'event_registrations': [
            ('team_id', 'INTEGER', None, True),
        ],
        'certificates': [
            ('extracted_name', 'VARCHAR(150)', None, True),
            ('confidence_score', 'FLOAT', '0.0', True),
            ('assigned_by_id', 'INTEGER', None, True),
            ('extracted_text', 'TEXT', None, True),
            ('file_type', 'VARCHAR(20)', "'pdf'", False),
            ('original_filename', 'VARCHAR(255)', None, True),
        ],
        'attendance_records': [
            ('session_id', 'INTEGER', None, True),
        ]
    }

    with engine.connect() as conn:
        for table_name, columns in specs.items():
            if table_name not in existing_tables:
                continue
            existing_cols = {c['name'] for c in inspector.get_columns(table_name)}
            for col_name, col_type, default_val, is_null in columns:
                if col_name not in existing_cols:
                    logger.info(f"Adding missing column '{col_name}' to '{table_name}' table...")
                    try:
                        null_clause = "NULL" if is_null else "NOT NULL"
                        default_clause = f" DEFAULT {default_val}" if default_val is not None else ""
                        
                        if 'postgres' in dialect:
                            sql = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col_name} {col_type}{default_clause} {null_clause}"
                        elif 'mssql' in dialect:
                            sql = f"ALTER TABLE [{table_name}] ADD [{col_name}] {col_type}{default_clause} {null_clause}"
                        else:
                            sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}{default_clause}"
                            
                        conn.execute(text(sql))
                        conn.commit()
                        logger.info(f"Successfully added column '{col_name}' to '{table_name}'.")
                    except Exception as e:
                        logger.warning(f"Note on adding {table_name}.{col_name}: {e}")
                        conn.rollback()

        # Safely backfill registration_start_date from created_at if NULL
        if 'event_requests' in existing_tables:
            try:
                conn.execute(text("UPDATE event_requests SET registration_start_date = created_at WHERE registration_start_date IS NULL"))
                conn.commit()
            except Exception as e:
                logger.warning(f"Note on backfilling event_requests.registration_start_date: {e}")
                conn.rollback()

        if 'events' in existing_tables:
            try:
                conn.execute(text("UPDATE events SET registration_start_date = created_at WHERE registration_start_date IS NULL"))
                conn.commit()
            except Exception as e:
                logger.warning(f"Note on backfilling events.registration_start_date: {e}")
                conn.rollback()




def _seed_departments():
    """Seeds the 8 standard college departments if departments table is empty."""
    try:
        existing_count = CollegeDepartment.query.count()
        if existing_count >= len(Department.CHOICES):
            return

        for code, name in Department.CHOICES:
            dept = CollegeDepartment.query.filter_by(code=code).first()
            if not dept:
                dept = CollegeDepartment(
                    code=code,
                    name=name,
                    description=f"Department of {name}",
                    is_active=True
                )
                db.session.add(dept)
                logger.info(f"Added department: {code} - {name}")
        db.session.commit()
    except Exception as e:
        logger.warning(f"Department seeding note: {e}")
        db.session.rollback()


def _seed_super_admin():
    """
    Ensures that at least one Super Admin account exists in the database.
    Credentials can be customized via environment variables:
      - SUPER_ADMIN_EMAIL (default: superadmin@college.edu)
      - SUPER_ADMIN_PASSWORD (default: Admin@123)
      - SUPER_ADMIN_NAME (default: Chief Super Admin)
      - SUPER_ADMIN_PHONE (default: +91 9840001122)
    """
    try:
        admin_email = os.environ.get('SUPER_ADMIN_EMAIL', 'superadmin@college.edu').strip().lower()
        admin_pass = os.environ.get('SUPER_ADMIN_PASSWORD', 'Admin@123')
        admin_name = os.environ.get('SUPER_ADMIN_NAME', 'Chief Super Admin').strip()
        admin_phone = os.environ.get('SUPER_ADMIN_PHONE', '+91 9840001122').strip()

        # Check if ANY super admin exists or if the specific email exists
        super_admin_exists = User.query.filter(
            (User.role == UserRole.SUPER_ADMIN) |
            (User.role == 'superadmin')
        ).first()

        target_user = User.query.filter_by(email=admin_email).first()

        if target_user:
            # If account exists but is not super_admin, promote it
            if not target_user.is_super_admin:
                target_user.role = UserRole.SUPER_ADMIN
                target_user.is_active = True
                if not target_user.faculty_profile:
                    db.session.add(FacultyProfile(
                        user_id=target_user.id,
                        employee_id="SUPER-ADMIN-01",
                        department="General",
                        designation="Super Administrator"
                    ))
                db.session.commit()
                logger.info(f"Promoted existing account {admin_email} to SUPER_ADMIN.")
            return

        if not super_admin_exists:
            # Create the initial Super Admin account
            new_admin = User(
                name=admin_name,
                email=admin_email,
                phone=admin_phone,
                role=UserRole.SUPER_ADMIN,
                is_active=True
            )
            new_admin.set_password(admin_pass)
            db.session.add(new_admin)
            db.session.flush()

            db.session.add(FacultyProfile(
                user_id=new_admin.id,
                employee_id="SUPER-ADMIN-01",
                department="General",
                designation="Super Administrator"
            ))
            db.session.commit()
            logger.info(f"Successfully provisioned initial Super Admin: {admin_email}")
    except Exception as e:
        logger.warning(f"Super admin seeding note: {e}")
        db.session.rollback()


def _seed_baseline_officials():
    """
    Seeds baseline Dean of Student Affairs and initial HOD accounts if none exist,
    ensuring the institutional two-stage approval workflow functions immediately.
    """
    try:
        # Dean of Student Affairs
        dean_exists = User.query.filter(
            (User.role == UserRole.STUDENTS_AFFAIRS_DEAN) |
            (User.role == 'dean')
        ).first()

        if not dean_exists:
            dean_email = os.environ.get('DEAN_EMAIL', 'dean@college.edu').strip().lower()
            dean_pass = os.environ.get('DEAN_PASSWORD', 'Dean@123')
            dean_name = os.environ.get('DEAN_NAME', 'Dr. S. K. Sharma (Dean)').strip()

            dean_user = User.query.filter_by(email=dean_email).first()
            if not dean_user:
                dean_user = User(
                    name=dean_name,
                    email=dean_email,
                    phone="+91 9840001133",
                    role=UserRole.STUDENTS_AFFAIRS_DEAN,
                    is_active=True
                )
                dean_user.set_password(dean_pass)
                db.session.add(dean_user)
                db.session.flush()
                db.session.add(FacultyProfile(
                    user_id=dean_user.id,
                    employee_id="DEAN-SA-01",
                    department="General",
                    designation="Dean of Student Affairs"
                ))
                db.session.commit()
                logger.info(f"Successfully provisioned baseline Dean: {dean_email}")

        # CSE Head of Department (HOD)
        cse_dept = CollegeDepartment.query.filter_by(code='CSE').first()
        if cse_dept and not cse_dept.hod_id:
            hod_email = os.environ.get('HOD_EMAIL', 'hod.cse@college.edu').strip().lower()
            hod_pass = os.environ.get('HOD_PASSWORD', 'Hod@123')
            hod_name = os.environ.get('HOD_NAME', 'Dr. K. Ramanathan (HOD CSE)').strip()

            hod_user = User.query.filter_by(email=hod_email).first()
            if not hod_user:
                hod_user = User(
                    name=hod_name,
                    email=hod_email,
                    phone="+91 9840001144",
                    role=UserRole.HOD,
                    is_active=True
                )
                hod_user.set_password(hod_pass)
                db.session.add(hod_user)
                db.session.flush()
                db.session.add(FacultyProfile(
                    user_id=hod_user.id,
                    employee_id="HOD-CSE-01",
                    department="CSE",
                    designation="Head of Department"
                ))
                cse_dept.hod_id = hod_user.id
                db.session.commit()
                logger.info(f"Successfully provisioned baseline CSE HOD: {hod_email}")
    except Exception as e:
        logger.warning(f"Baseline officials seeding note: {e}")
        db.session.rollback()
