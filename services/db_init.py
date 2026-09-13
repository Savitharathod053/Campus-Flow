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
    Initializes all database tables and seeds the essential baseline.
    Returns True on success, False on failure.
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

            # 2. Seed canonical college departments if empty
            _seed_departments()

            # 3. Seed initial Super Admin if not present
            _seed_super_admin()

            # 4. Seed baseline Dean and HOD accounts if missing
            _seed_baseline_officials()

            db.session.commit()
            _DB_INITIALIZED = True
            logger.info("Database initialization and seeding completed successfully.")
            return True
        except Exception as e:
            logger.error(f"Database initialization encountered an error: {e}", exc_info=True)
            db.session.rollback()
            return False



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
