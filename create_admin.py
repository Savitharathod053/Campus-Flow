"""
Campus Flow - Production Admin Creation Script

Creates the initial system administrator (Faculty Admin) with securely hashed credentials.
Do NOT hard-code passwords or use default credentials.

Usage:
  python create_admin.py
  python create_admin.py --name "Admin Name" --email "admin@college.edu" --password "SecurePass"
"""

import sys
import getpass
import argparse
from app import create_app
from models import db, User, UserRole, FacultyProfile

def create_admin(name=None, email=None, password=None, department="General", phone=None, employee_id=None, designation="Dean / Administrator"):
    app = create_app()
    with app.app_context():
        print("=" * 60)
        print("        CAMPUS FLOW - SECURE ADMINISTRATOR CREATION")
        print("=" * 60)

        if not name:
            name = input("Enter Administrator Full Name: ").strip()
        if not email:
            email = input("Enter Administrator Email: ").strip().lower()
        if not password:
            while True:
                password = getpass.getpass("Enter Secure Password (min 8 characters): ")
                confirm_password = getpass.getpass("Confirm Password: ")
                if password != confirm_password:
                    print("Passwords do not match. Please try again.\n")
                elif len(password) < 8:
                    print("Password is too short (minimum 8 characters). Please try again.\n")
                else:
                    break

        if not name or not email or not password:
            print("Error: Name, email, and password are required.")
            return False

        # Check if user with this email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print(f"User with email '{email}' already exists (Role: {existing_user.role}).")
            if existing_user.role != UserRole.FACULTY_ADMIN:
                promote = input("Promote existing user to FACULTY_ADMIN? (y/N): ").strip().lower()
                if promote == 'y':
                    existing_user.role = UserRole.FACULTY_ADMIN
                    existing_user.is_active = True
                    if not existing_user.faculty_profile:
                        fp = FacultyProfile(
                            user_id=existing_user.id,
                            department=department,
                            employee_id=employee_id or f"FAC-{existing_user.id:04d}",
                            designation=designation
                        )
                        db.session.add(fp)
                    db.session.commit()
                    print(f"User '{email}' successfully promoted to Administrator.")
                    return True
            return False

        # Create new admin user
        admin_user = User(
            name=name,
            email=email,
            phone=phone,
            role=UserRole.FACULTY_ADMIN,
            is_active=True
        )
        admin_user.set_password(password)
        db.session.add(admin_user)
        db.session.flush()

        faculty_prof = FacultyProfile(
            user_id=admin_user.id,
            department=department,
            employee_id=employee_id or f"ADMIN-{admin_user.id:04d}",
            designation=designation
        )
        db.session.add(faculty_prof)
        db.session.commit()

        print("\n" + "=" * 60)
        print(f" SUCCESS: Administrator account '{email}' created successfully!")
        print(" Role: Faculty Administrator (FACULTY_ADMIN)")
        print(f" Department: {department}")
        print("=" * 60 + "\n")
        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create Campus Flow Administrator")
    parser.add_argument("--name", help="Administrator Full Name")
    parser.add_argument("--email", help="Administrator Email")
    parser.add_argument("--password", help="Secure Password")
    parser.add_argument("--department", default="General", help="Department: CSE, IT, CSD, CSM, ECE, EEE, MECH, CIVILS, General (default: General)")
    parser.add_argument("--phone", default=None, help="Contact Phone Number")
    parser.add_argument("--employee-id", default=None, help="Employee ID")
    parser.add_argument("--designation", default="Dean / Chief Administrator", help="Designation")

    args = parser.parse_args()
    create_admin(
        name=args.name,
        email=args.email,
        password=args.password,
        department=args.department,
        phone=args.phone,
        employee_id=args.employee_id,
        designation=args.designation
    )
