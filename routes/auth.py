from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g
from models import db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)


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
                flash('Access denied. You do not have permission for this portal.', 'danger')
                return redirect(url_for('public.home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def student_required(f):
    return login_required(role_required(UserRole.STUDENT)(f))


def organizer_required(f):
    return login_required(role_required(UserRole.ORGANIZER)(f))


def admin_required(f):
    return login_required(role_required(UserRole.FACULTY_ADMIN)(f))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        user = get_current_user()
        if user:
            if user.is_student:
                return redirect(url_for('student.dashboard'))
            elif user.is_organizer:
                return redirect(url_for('organizer.dashboard'))
            elif user.is_admin:
                return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'

        if not email or not password:
            flash('Email and password are required.', 'danger')
            return render_template('auth/login.html')

        user = User.query.filter_by(email=email).first()

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

        if user.is_student:
            return redirect(url_for('student.dashboard'))
        elif user.is_organizer:
            return redirect(url_for('organizer.dashboard'))
        elif user.is_admin:
            return redirect(url_for('admin.dashboard'))

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
        organization_name = request.form.get('organization_name', '').strip()
        department = request.form.get('department', '').strip()
        designation = request.form.get('designation', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not all([name, email, organization_name, department, password]):
            flash('Please fill in all required fields.', 'danger')
            return render_template('auth/register_organizer.html', department_admins=department_admins)

        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register_organizer.html', department_admins=department_admins)

        if User.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'danger')
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
