"""
Campus Flow - Super Admin CLI Creator Script
Usage:
    python create_super_admin.py --email admin@college.edu --password MyPassword123
    python create_super_admin.py --default
    python create_super_admin.py (interactive prompt)
"""
import sys
import argparse
from app import create_app
from models import db, User, UserRole, FacultyProfile
from services.audit_service import log_audit_action

def create_or_promote_super_admin(email, password, name=None, phone=None):
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(email=email.lower().strip()).first()

        if user:
            print(f"User with email '{user.email}' already exists (Current Role: {user.role}).")
            user.role = UserRole.SUPER_ADMIN
            user.is_active = True
            if name:
                user.name = name
            if phone:
                user.phone = phone
            if password:
                user.set_password(password)
            
            db.session.commit()
            print(f"SUCCESS: Promoted existing user '{user.name}' ({user.email}) to SUPER_ADMIN!")
            return user
        else:
            name = name or "System Super Administrator"
            phone = phone or "+91 9999900000"
            new_user = User(
                name=name,
                email=email.lower().strip(),
                phone=phone,
                role=UserRole.SUPER_ADMIN,
                is_active=True
            )
            new_user.set_password(password or "Admin@123")
            db.session.add(new_user)
            db.session.flush()

            # Add general administration faculty profile
            fp = FacultyProfile(
                user_id=new_user.id,
                employee_id="SUPER-ADMIN-01",
                department="General",
                designation="Super Administrator"
            )
            db.session.add(fp)
            db.session.commit()

            print(f"SUCCESS: Created new SUPER_ADMIN user '{new_user.name}' ({new_user.email})!")
            return new_user

def main():
    parser = argparse.ArgumentParser(description="Create or promote a Campus Flow user to Super Admin.")
    parser.add_argument("--email", help="Super Admin Email address")
    parser.add_argument("--password", help="Super Admin Password")
    parser.add_argument("--name", help="Full Name of Admin")
    parser.add_argument("--phone", help="Contact phone number")
    parser.add_argument("--default", action="store_true", help="Create default superadmin@college.edu / Admin@123")

    args = parser.parse_args()

    if args.default:
        email = "superadmin@college.edu"
        password = "Admin@123"
        name = "Chief Super Admin"
        phone = "+91 9840001122"
    elif args.email:
        email = args.email
        password = args.password
        if not password:
            import getpass
            password = getpass.getpass("Enter password for Super Admin: ")
        name = args.name
        phone = args.phone
    else:
        # Prompt interactively
        print("\n--- Campus Flow Super Admin Setup ---")
        email = input("Enter Super Admin email [default: superadmin@college.edu]: ").strip() or "superadmin@college.edu"
        import getpass
        password = getpass.getpass("Enter Super Admin password [default: Admin@123]: ").strip() or "Admin@123"
        name = input("Enter Full Name [default: Chief Super Admin]: ").strip() or "Chief Super Admin"
        phone = input("Enter Phone Number [default: +91 9840001122]: ").strip() or "+91 9840001122"

    create_or_promote_super_admin(email, password, name, phone)

if __name__ == "__main__":
    main()
