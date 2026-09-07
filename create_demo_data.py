#!/usr/bin/env python3
"""
Campus Flow - Demo Data Creator (Faculty / Organizer / Student)
=================================================================
Adds ONE demo account for each role directly into your existing
Microsoft SQL Server (SSMS) database, using the same models and
password hashing as the rest of the app (werkzeug's secure hash) so
the accounts can log in normally through the website.

This script is NON-DESTRUCTIVE: it does NOT drop or clear any
existing tables or data (unlike seed_data.py / reset_database.py).
It is also safe to re-run - if a demo account's email already
exists, that account is skipped instead of duplicated.

Usage:
  python create_demo_data.py
"""

from app import create_app
from models import db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile

DEMO_PASSWORD = "Demo@123"


def _create_user_if_missing(email, name, phone, role):
    existing = User.query.filter_by(email=email).first()
    if existing:
        print(f"  [skip] '{email}' already exists (role: {existing.role}).")
        return existing, False

    user = User(name=name, email=email, phone=phone, role=role, is_active=True)
    user.set_password(DEMO_PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user, True


def create_demo_data():
    app = create_app()
    with app.app_context():
        print("=" * 70)
        print("   CAMPUS FLOW - CREATING DEMO FACULTY / ORGANIZER / STUDENT")
        print("=" * 70)

        # ------------------------------------------------------------
        # 1. FACULTY (Faculty Admin)
        # ------------------------------------------------------------
        print("\n[1/3] Faculty demo account...")
        faculty_user, created = _create_user_if_missing(
            email="faculty.demo@college.edu",
            name="Dr. Demo Faculty",
            phone="+91 9800000001",
            role=UserRole.FACULTY_ADMIN,
        )
        if created:
            db.session.add(FacultyProfile(
                user_id=faculty_user.id,
                employee_id="FAC-DEMO-001",
                department="CSE",
                designation="Assistant Professor & Faculty Admin",
            ))
            db.session.commit()
            print(f"  [+] Created faculty account: {faculty_user.email}")

        # ------------------------------------------------------------
        # 2. ORGANIZER (approved, so they can create events right away)
        # ------------------------------------------------------------
        print("\n[2/3] Organizer demo account...")
        organizer_user, created = _create_user_if_missing(
            email="organizer.demo@college.edu",
            name="Demo Organizer",
            phone="+91 9800000002",
            role=UserRole.ORGANIZER,
        )
        if created:
            db.session.add(OrganizerProfile(
                user_id=organizer_user.id,
                organization_name="Demo Events Club",
                department="CSE",
                designation="Coordinator",
                is_verified=True,
                status="APPROVED",
                approved_by_id=faculty_user.id,
            ))
            db.session.commit()
            print(f"  [+] Created organizer account: {organizer_user.email}")

        # ------------------------------------------------------------
        # 3. STUDENT
        # ------------------------------------------------------------
        print("\n[3/3] Student demo account...")
        student_user, created = _create_user_if_missing(
            email="student.demo@college.edu",
            name="Demo Student",
            phone="+91 9800000003",
            role=UserRole.STUDENT,
        )
        if created:
            db.session.add(StudentProfile(
                user_id=student_user.id,
                roll_number="DEMO2026CS001",
                department="CSE",
                year=2,
                section="A",
            ))
            db.session.commit()
            print(f"  [+] Created student account: {student_user.email}")

        print("\n" + "=" * 70)
        print(" DONE. Demo login credentials (password is the same for all):")
        print("-" * 70)
        print(f"  Faculty Admin:  faculty.demo@college.edu   / {DEMO_PASSWORD}")
        print(f"  Organizer:      organizer.demo@college.edu / {DEMO_PASSWORD}")
        print(f"  Student:        student.demo@college.edu   / {DEMO_PASSWORD}")
        print("=" * 70)


if __name__ == "__main__":
    create_demo_data()
