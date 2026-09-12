from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, abort, current_app
from models import db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    try:
        user = db.session.get(User, user_id)
        if not user:
            # Stale session detected: user id does not exist in the database
            session.pop('user_id', None)
            return None
        return user
    except Exception as e:
        import logging
        logging.getLogger('CampusFlow.Auth').error(
            f"Database error in get_current_user (user_id={user_id}): {e}", exc_info=True
        )
        return None


def get_department_faculty_admins():
    """
    Returns a dictionary of department -> Faculty User object
    """
    faculty_profiles = FacultyProfile.query.all()
    admins_by_dept = {}
    for fp in faculty_profiles:
        admins_by_dept[fp.department] = {
            'name': fp.user.name,
            'email': fp.user.email,
            'phone': fp.user.phone,
            'designation': fp.designation,
            'department': fp.department,
            'employee_id': fp.employee_id
        }
    return admins_by_dept


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        user = get_current_user()
        if not user or not user.is_active:
            session.clear()
            flash('Your account is inactive or not found.', 'danger')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('user_id'):
                flash('Please log in first.', 'warning')
                return redirect(url_for('auth.login', next=request.url))
            user = get_current_user()
            if not user or user.role not in allowed_roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def student_required(f):
    return login_required(role_required(UserRole.STUDENT)(f))


def organizer_required(f):
    return login_required(role_required(UserRole.ORGANIZER)(f))


def hod_required(f):
    return login_required(role_required(UserRole.HOD)(f))


def dean_required(f):
    return login_required(role_required(UserRole.STUDENTS_AFFAIRS_DEAN)(f))

students_affairs_dean_required = dean_required


def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please log in to access the Super Admin portal.', 'warning')
            return redirect(url_for('auth.login', next=request.url))
        user = get_current_user()
        if not user or not user.is_active:
            session.clear()
            flash('Your account is inactive or not found.', 'danger')
            return redirect(url_for('auth.login'))
        if not user.is_super_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# Backward compatibility aliases
admin_required = super_admin_required
faculty_required = hod_required


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        user = get_current_user()
        if user:
            if user.is_super_admin:
                return redirect(url_for('admin.dashboard'))
            elif user.is_students_affairs_dean:
                return redirect(url_for('dean.dashboard'))
            elif user.is_hod:
                return redirect(url_for('hod.dashboard'))
            elif user.is_student:
                return redirect(url_for('student.dashboard'))
            elif user.is_organizer:
                return redirect(url_for('organizer.dashboard'))

    if request.method == 'POST':
        identifier = (request.form.get('identifier') or request.form.get('email') or request.form.get('roll_number') or '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        if not identifier or not password:
            flash('Roll number / email and password are required.', 'danger')
            return render_template('auth/login.html')

        user = None

        # Resolution order:
        # 1. First try StudentProfile.query.filter_by(roll_number=identifier).first() -> use .user
        student_profile = StudentProfile.query.filter_by(roll_number=identifier).first()
        if not student_profile and hasattr(identifier, 'upper'):
            student_profile = StudentProfile.query.filter_by(roll_number=identifier.upper()).first()

        if student_profile:
            user = student_profile.user
        else:
            # 2. Then try OrganizerProfile.query.filter_by(roll_number=identifier).first() -> use .user
            organizer_profile = OrganizerProfile.query.filter_by(roll_number=identifier).first()
            if not organizer_profile and hasattr(identifier, 'upper'):
                organizer_profile = OrganizerProfile.query.filter_by(roll_number=identifier.upper()).first()

            if organizer_profile:
                user = organizer_profile.user
            else:
                # 3. Fall back to User.query.filter_by(email=identifier).first() (kept only for HOD/Dean/Super Admin, who have no roll number)
                candidate_user = User.query.filter_by(email=identifier.lower()).first()
                if not candidate_user:
                    candidate_user = User.query.filter_by(email=identifier).first()
                # Email is no longer a valid login credential for students and organizers
                if candidate_user and not (candidate_user.is_student or candidate_user.is_organizer):
                    user = candidate_user

        if not user or not user.check_password(password):
            flash('Invalid email or password credentials.', 'danger')
            return render_template('auth/login.html')

        if not user.is_active:
            flash('Your account has been deactivated by the faculty admin.', 'danger')
            return render_template('auth/login.html')

        # Check Organizer Verification & Approval
        if user.is_organizer and user.organizer_profile:
            if not user.organizer_profile.is_verified:
                dept = user.organizer_profile.department
                # Find department admin
                faculty_admin = FacultyProfile.query.filter_by(department=dept).first()
                if not faculty_admin:
                    faculty_admin = FacultyProfile.query.filter_by(department='General').first()
                admin_name = faculty_admin.user.name if faculty_admin else 'Department Faculty Coordinator'
                admin_email = faculty_admin.user.email if faculty_admin else 'admin@college.edu'

                if user.organizer_profile.status == 'REJECTED':
                    reason = user.organizer_profile.rejection_reason or 'Guidelines not met.'
                    flash(f"Your organizer registration was rejected by {admin_name} ({admin_email}). Reason: {reason}", 'danger')
                else:
                    flash(f"Your organizer account is pending approval by your department faculty admin: {admin_name} ({admin_email}) for {dept} department. Please contact your department admin to approve your account.", 'warning')
                return render_template('auth/login.html')

        session.clear()
        session['user_id'] = user.id
        session['user_role'] = user.role
        session['user_name'] = user.name
        session.permanent = remember

        flash(f'Welcome back, {user.name}!', 'success')

        next_page = request.args.get('next')
        if next_page and next_page.startswith('/'):
            return redirect(next_page)

        if user.is_super_admin:
            return redirect(url_for('admin.dashboard'))
        elif user.is_students_affairs_dean:
            return redirect(url_for('dean.dashboard'))
        elif user.is_hod:
            return redirect(url_for('hod.dashboard'))
        elif user.is_student:
            return redirect(url_for('student.dashboard'))
        elif user.is_organizer:
            return redirect(url_for('organizer.dashboard'))

        return redirect(url_for('public.home'))

    return render_template('auth/login.html')


@auth_bp.route('/register/student', methods=['GET', 'POST'])
def register_student():
    if session.get('user_id'):
        return redirect(url_for('public.home'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        roll_number = request.form.get('roll_number', '').strip().upper()
        department = request.form.get('department', '').strip()
        year = request.form.get('year', '').strip()
        section = request.form.get('section', '').strip().upper()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        # Validations
        if not all([name, email, roll_number, department, year, section, password]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('auth/register_student.html')

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register_student.html')

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('auth/register_student.html')

        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            return render_template('auth/register_student.html')

        if StudentProfile.query.filter_by(roll_number=roll_number).first():
            flash('A student with this Roll Number is already registered.', 'danger')
            return render_template('auth/register_student.html')

        try:
            year_int = int(year)
        except ValueError:
            year_int = 1

        # Create user & profile
        user = User(
            name=name,
            email=email,
            phone=phone,
            role=UserRole.STUDENT,
            is_active=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        profile = StudentProfile(
            user_id=user.id,
            roll_number=roll_number,
            department=department,
            year=year_int,
            section=section
        )
        db.session.add(profile)
        db.session.commit()

        # Send welcome email (asynchronous / non-blocking, safe from failure)
        try:
            from services.email_service import send_account_registration_email
            send_account_registration_email(user)
        except Exception as exc:
            current_app.logger.warning(f"Could not dispatch student registration email: {exc}")

        flash('Registration successful! You can now log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register_student.html')


@auth_bp.route('/register/organizer', methods=['GET', 'POST'])
def register_organizer():
    if session.get('user_id'):
        return redirect(url_for('public.home'))

    department_admins = get_department_faculty_admins()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        roll_number = request.form.get('roll_number', '').strip().upper()
        organization_name = request.form.get('organization_name', '').strip()
        department = request.form.get('department', '').strip()
        designation = request.form.get('designation', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not all([name, email, roll_number, organization_name, department, password]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('auth/register_organizer.html', department_admins=department_admins)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register_organizer.html', department_admins=department_admins)

        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('auth/register_organizer.html', department_admins=department_admins)

        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
            return render_template('auth/register_organizer.html', department_admins=department_admins)

        if OrganizerProfile.query.filter_by(roll_number=roll_number).first() or StudentProfile.query.filter_by(roll_number=roll_number).first():
            flash('An account with this Roll Number is already registered.', 'danger')
            return render_template('auth/register_organizer.html', department_admins=department_admins)

        # Create user as Organizer with is_verified=False (Pending Admin Approval)
        user = User(
            name=name,
            email=email,
            phone=phone,
            role=UserRole.ORGANIZER,
            is_active=True
        )
        user.set_password(password)
        db.session.add(user)
        db.session.flush()

        profile = OrganizerProfile(
            user_id=user.id,
            roll_number=roll_number,
            organization_name=organization_name,
            department=department,
            designation=designation,
            is_verified=False,
            status='PENDING'
        )
        db.session.add(profile)
        db.session.commit()

        # Find the specific faculty admin for this department
        assigned_admin = department_admins.get(department)
        admin_name = assigned_admin['name'] if assigned_admin else 'Department Faculty Coordinator'
        admin_email = assigned_admin['email'] if assigned_admin else 'admin@college.edu'

        # Dispatch emails & notifications (safely caught)
        try:
            from services.email_service import (
                send_organizer_application_received_email,
                send_organizer_registration_faculty_notice_email
            )
            from services.notification_service import create_notification
            from models.notification import NotificationType
            from models import CollegeDepartment

            # Identify HOD / Faculty Admin for department
            dept_obj = CollegeDepartment.query.filter(
                (CollegeDepartment.name == department) | (CollegeDepartment.code == department)
            ).first()
            hod_user = dept_obj.hod if dept_obj else None

            # Fallback to faculty profile user if no hod
            faculty_user = hod_user
            if not faculty_user and assigned_admin:
                faculty_user = User.query.filter_by(email=assigned_admin['email']).first()

            # 1. Confirmation to applicant
            send_organizer_application_received_email(
                user,
                profile_or_req=profile,
                assigned_admin_name=faculty_user.name if faculty_user else admin_name
            )

            # 2. Heads-up to faculty admin / HOD
            if faculty_user:
                create_notification(
                    user_id=faculty_user.id,
                    title=f"New Organizer Registration: {user.name}",
                    message=f"Student {user.name} (Roll: {roll_number}) has registered as an organizer for {department} and is waiting for approval.",
                    notification_type=NotificationType.ORGANIZER_REQUEST,
                    link=url_for('hod.dashboard', tab='org_pending') if faculty_user.role == UserRole.HOD else url_for('admin.users_organizers')
                )
                send_organizer_registration_faculty_notice_email(
                    applicant_user=user,
                    faculty_user=faculty_user,
                    department_name=department,
                    profile=profile
                )
        except Exception as exc:
            current_app.logger.warning(f"Could not dispatch organizer registration notifications: {exc}")

        flash(f"Organizer registration submitted successfully! Your application has been forwarded to your department faculty admin: {admin_name} ({admin_email}) for approval. You can log in once approved.", 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/register_organizer.html', department_admins=department_admins)


@auth_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = get_current_user()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        new_password = request.form.get('new_password', '')

        if name:
            user.name = name
        user.phone = phone

        if new_password:
            if len(new_password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return render_template('auth/profile.html', user=user)
            user.set_password(new_password)

        if user.is_student and user.student_profile:
            user.student_profile.department = request.form.get('department', user.student_profile.department)
            user.student_profile.section = request.form.get('section', user.student_profile.section).upper()
            try:
                user.student_profile.year = int(request.form.get('year', user.student_profile.year))
            except ValueError:
                pass

        elif user.is_organizer and user.organizer_profile:
            user.organizer_profile.organization_name = request.form.get('organization_name', user.organizer_profile.organization_name)
            user.organizer_profile.department = request.form.get('department', user.organizer_profile.department)
            user.organizer_profile.designation = request.form.get('designation', user.organizer_profile.designation)

        elif user.is_admin and user.faculty_profile:
            user.faculty_profile.department = request.form.get('department', user.faculty_profile.department)
            user.faculty_profile.designation = request.form.get('designation', user.faculty_profile.designation)

        db.session.commit()
        session['user_name'] = user.name
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('auth.profile'))

    return render_template('auth/profile.html', user=user)


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out safely.', 'info')
    return redirect(url_for('public.home'))
