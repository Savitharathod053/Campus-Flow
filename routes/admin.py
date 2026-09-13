import json
from datetime import datetime, timedelta
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash,
    jsonify, abort, Response, current_app, send_file
)
from sqlalchemy import func, or_
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    Payment, PaymentStatus, AttendanceRecord, AttendanceStatus, VerificationMethod,
    Certificate, CertificateStatus, Announcement, TargetAudience,
    CollegeDepartment, Department, AuditLog,
    OrganizerRequest, OrganizerRequestStatus, EventRequest, EventRequestStatus,
    Team, TeamMember, TeamInvitation
)
from routes.auth import admin_required, get_current_user
super_admin_required = admin_required
from services.audit_service import log_audit_action
from services.import_service import parse_file_rows, validate_import_data, execute_import, generate_sample_csv
from services.event_service import delete_event_with_cleanup, are_certificates_completed, delete_expired_events
from services.cert_service import generate_certificate_image
from services.db_diagnostic import get_safe_db_info

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def normalize_role(role_input):
    if not role_input:
        return UserRole.STUDENT
    val = str(role_input).strip().lower()
    role_map = {
        'super_admin': UserRole.SUPER_ADMIN,
        'admin': UserRole.SUPER_ADMIN,
        'students_affairs_dean': UserRole.STUDENTS_AFFAIRS_DEAN,
        'dean': UserRole.STUDENTS_AFFAIRS_DEAN,
        'hod': UserRole.HOD,
        'faculty': UserRole.HOD,
        'faculty_admin': UserRole.HOD,
        'organizer': UserRole.ORGANIZER,
        'student': UserRole.STUDENT,
    }
    return role_map.get(val, val)



# ==============================================================================
# 1. DASHBOARD & SYSTEM OVERVIEW (SUPER ADMIN)
# ==============================================================================
@admin_bp.route('/')
@admin_bp.route('/dashboard')
@super_admin_required
def dashboard():
    user = get_current_user()

    # User Counts (Exact 5 Canonical Roles)
    total_users = User.query.count()
    total_super_admins = User.query.filter(User.role.in_([UserRole.SUPER_ADMIN, 'super_admin', 'ADMIN', 'admin'])).count()
    total_deans = User.query.filter(User.role.in_([UserRole.STUDENTS_AFFAIRS_DEAN, 'students_affairs_dean', 'dean', 'DEAN'])).count()
    total_hods = User.query.filter(User.role.in_([UserRole.HOD, 'hod', 'HOD'])).count()
    total_organizers = User.query.filter(User.role.in_([UserRole.ORGANIZER, 'organizer', 'ORGANIZER'])).count()
    total_students = User.query.filter(User.role.in_([UserRole.STUDENT, 'student', 'STUDENT'])).count()

    # Display variables
    total_faculty = total_hods
    total_admins = total_super_admins

    # Operations Counts
    total_events = Event.query.count()
    pending_events = EventRequest.query.filter(
        EventRequest.overall_status.in_([EventRequestStatus.PENDING_HOD_APPROVAL, EventRequestStatus.PENDING_DEAN_APPROVAL])
    ).count()
    active_events = Event.query.filter(Event.is_published == True, Event.status.in_([EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN])).count()
    completed_events = Event.query.filter_by(status=EventStatus.EVENT_COMPLETED).count()

    total_registrations = EventRegistration.query.count()
    confirmed_registrations = EventRegistration.query.filter_by(status=RegistrationStatus.CONFIRMED).count()

    total_payments = Payment.query.count()
    total_revenue = db.session.query(func.sum(Payment.amount)).filter(Payment.status.in_([PaymentStatus.VERIFIED, 'SUCCESS'])).scalar() or 0.0

    total_certificates = Certificate.query.count()
    total_attendance = AttendanceRecord.query.count()
    total_departments = CollegeDepartment.query.filter_by(is_active=True).count()

    # Department-wise Registration Breakdown for Charts
    dept_reg_stats = db.session.query(
        StudentProfile.department,
        func.count(EventRegistration.id).label('count')
    ).join(User, StudentProfile.user_id == User.id)\
     .join(EventRegistration, EventRegistration.student_id == User.id)\
     .filter(EventRegistration.status == RegistrationStatus.CONFIRMED)\
     .group_by(StudentProfile.department).all()

    dept_chart_labels = [row[0] for row in dept_reg_stats]
    dept_chart_data = [row[1] for row in dept_reg_stats]

    # Recent Registrations
    recent_registrations = EventRegistration.query.order_by(EventRegistration.created_at.desc()).limit(6).all()

    # Recent Audit Logs
    recent_audit_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all()

    # Pending Event Creation Requests across college
    pending_events_list = EventRequest.query.filter(
        EventRequest.overall_status.in_([EventRequestStatus.PENDING_HOD_APPROVAL, EventRequestStatus.PENDING_DEAN_APPROVAL])
    ).order_by(EventRequest.created_at.desc()).limit(6).all()

    # Pending Organizer Requests across college
    pending_organizers_list = OrganizerRequest.query.filter_by(status=OrganizerRequestStatus.PENDING)\
        .order_by(OrganizerRequest.created_at.desc()).limit(6).all()

    return render_template(
        'admin/dashboard.html',
        user=user,
        total_users=total_users,
        total_super_admins=total_super_admins,
        total_deans=total_deans,
        total_students=total_students,
        total_faculty=total_faculty,
        total_hods=total_hods,
        total_organizers=total_organizers,
        total_admins=total_admins,
        total_events=total_events,
        pending_events=pending_events,
        active_events=active_events,
        completed_events=completed_events,
        total_registrations=total_registrations,
        confirmed_registrations=confirmed_registrations,
        total_payments=total_payments,
        total_revenue=total_revenue,
        total_certificates=total_certificates,
        total_attendance=total_attendance,
        total_departments=total_departments,
        dept_chart_labels=json.dumps(dept_chart_labels),
        dept_chart_data=json.dumps(dept_chart_data),
        recent_registrations=recent_registrations,
        recent_audit_logs=recent_audit_logs,
        pending_events_list=pending_events_list,
        pending_organizers_list=pending_organizers_list
    )


# ==============================================================================
# 2. GLOBAL SEARCH
# ==============================================================================
@admin_bp.route('/search')
@super_admin_required
def global_search():
    user = get_current_user()
    q = request.args.get('q', '').strip()

    results = {
        'users': [],
        'events': [],
        'registrations': [],
        'certificates': []
    }

    if q:
        # Search Users by name, email, phone, roll_number, employee_id
        user_matches = db.session.query(User).outerjoin(StudentProfile).outerjoin(FacultyProfile).filter(
            or_(
                User.name.ilike(f'%{q}%'),
                User.email.ilike(f'%{q}%'),
                User.phone.ilike(f'%{q}%'),
                StudentProfile.roll_number.ilike(f'%{q}%'),
                FacultyProfile.employee_id.ilike(f'%{q}%')
            )
        ).limit(15).all()
        results['users'] = user_matches

        # Search Events by title, venue, department
        event_matches = Event.query.filter(
            or_(
                Event.title.ilike(f'%{q}%'),
                Event.venue.ilike(f'%{q}%'),
                Event.department.ilike(f'%{q}%')
            )
        ).limit(15).all()
        results['events'] = event_matches

        # Search Registrations by code or student name
        reg_matches = EventRegistration.query.join(User).filter(
            or_(
                EventRegistration.registration_code.ilike(f'%{q}%'),
                User.name.ilike(f'%{q}%')
            )
        ).limit(15).all()
        results['registrations'] = reg_matches

        # Search Certificates by code or roll number
        cert_matches = Certificate.query.filter(
            or_(
                Certificate.certificate_code.ilike(f'%{q}%'),
                Certificate.roll_number.ilike(f'%{q}%')
            )
        ).limit(15).all()
        results['certificates'] = cert_matches

    total_matches = len(results['users']) + len(results['events']) + len(results['registrations']) + len(results['certificates'])

    return render_template('admin/search/index.html', user=user, q=q, results=results, total_matches=total_matches)


# ==============================================================================
# 3. USER MANAGEMENT (LIST, FILTER, ADD, EDIT, DELETE, RESET PASSWORD)
# ==============================================================================
@admin_bp.route('/users')
@super_admin_required
def users_list():
    user = get_current_user()
    role_filter = request.args.get('role', 'ALL').strip()
    dept_filter = request.args.get('dept', 'ALL').strip()
    status_filter = request.args.get('status', 'ALL').strip().upper()
    search = request.args.get('q', '').strip()
    sort_by = request.args.get('sort', 'created_desc')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = User.query.outerjoin(StudentProfile).outerjoin(FacultyProfile).outerjoin(OrganizerProfile, User.id == OrganizerProfile.user_id)

    # Role filter
    if role_filter.upper() != 'ALL':
        mapped_role = normalize_role(role_filter)
        if mapped_role == UserRole.SUPER_ADMIN:
            query = query.filter(User.role.in_([UserRole.SUPER_ADMIN, 'super_admin', 'ADMIN', 'admin']))
        elif mapped_role == UserRole.HOD:
            query = query.filter(User.role.in_([UserRole.HOD, 'hod', 'FACULTY', 'faculty', 'FACULTY_ADMIN']))
        elif mapped_role == UserRole.STUDENTS_AFFAIRS_DEAN:
            query = query.filter(User.role.in_([UserRole.STUDENTS_AFFAIRS_DEAN, 'students_affairs_dean', 'dean']))
        elif mapped_role == UserRole.ORGANIZER:
            query = query.filter(User.role.in_([UserRole.ORGANIZER, 'organizer', 'ORGANIZER']))
        elif mapped_role == UserRole.STUDENT:
            query = query.filter(User.role.in_([UserRole.STUDENT, 'student', 'STUDENT']))
        else:
            query = query.filter(func.lower(User.role) == mapped_role.lower())

    # Status filter
    if status_filter == 'ACTIVE':
        query = query.filter(User.is_active.is_(True))
    elif status_filter == 'INACTIVE':
        query = query.filter(User.is_active.is_(False))

    # Department filter
    if dept_filter != 'ALL' and dept_filter:
        query = query.filter(
            or_(
                StudentProfile.department == dept_filter,
                FacultyProfile.department == dept_filter,
                OrganizerProfile.department == dept_filter
            )
        )

    # Search filter
    if search:
        query = query.filter(
            or_(
                User.name.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
                User.phone.ilike(f'%{search}%'),
                StudentProfile.roll_number.ilike(f'%{search}%'),
                FacultyProfile.employee_id.ilike(f'%{search}%')
            )
        )

    # Sorting
    if sort_by == 'name_asc':
        query = query.order_by(User.name.asc())
    elif sort_by == 'name_desc':
        query = query.order_by(User.name.desc())
    elif sort_by == 'created_asc':
        query = query.order_by(User.created_at.asc())
    else:
        query = query.order_by(User.created_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    users = pagination.items

    departments = CollegeDepartment.query.filter_by(is_active=True).all()
    roles = UserRole.CHOICES

    return render_template(
        'admin/users/index.html',
        user=user,
        users=users,
        pagination=pagination,
        role_filter=role_filter,
        dept_filter=dept_filter,
        status_filter=status_filter,
        search=search,
        sort_by=sort_by,
        departments=departments,
        roles=roles
    )


# Role Quick-Link Routes
@admin_bp.route('/users/students')
@super_admin_required
def users_students():
    return redirect(url_for('admin.users_list', role='STUDENT'))


@admin_bp.route('/users/deans')
@super_admin_required
def users_deans():
    return redirect(url_for('admin.users_list', role='STUDENTS_AFFAIRS_DEAN'))


@admin_bp.route('/users/faculty')
@super_admin_required
def users_faculty():
    return redirect(url_for('admin.users_list', role='FACULTY'))


@admin_bp.route('/users/hods')
@super_admin_required
def users_hods():
    return redirect(url_for('admin.users_list', role='HOD'))


@admin_bp.route('/users/organizers')
@super_admin_required
def users_organizers():
    return redirect(url_for('admin.users_list', role='ORGANIZER'))


@admin_bp.route('/users/admins')
@super_admin_required
def users_admins():
    return redirect(url_for('admin.users_list', role='ADMIN'))


@admin_bp.route('/faculty-directory')
@super_admin_required
def faculty_list():
    return redirect(url_for('admin.users_list', role='HOD'))


@admin_bp.route('/students-directory')
@super_admin_required
def students_list():
    return redirect(url_for('admin.users_list', role='STUDENT'))


@admin_bp.route('/pending-approvals')
@super_admin_required
def pending_approvals():
    tab = request.args.get('tab', 'events')
    if tab == 'organizers':
        return redirect(url_for('admin.organizer_requests_list'))
    return redirect(url_for('admin.event_requests_list'))


@admin_bp.route('/import-faculty', methods=['GET', 'POST'])
@super_admin_required
def import_faculty():
    return redirect(url_for('admin.import_users'))


@admin_bp.route('/import-students', methods=['GET', 'POST'])
@super_admin_required
def import_students():
    return redirect(url_for('admin.import_users'))


# Add User
@admin_bp.route('/users/add', methods=['GET', 'POST'])
@super_admin_required
def user_add():
    user = get_current_user()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        role = normalize_role(request.form.get('role', UserRole.STUDENT))
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()

        if not name or not email or not password:
            flash('Name, Email, and Password are required.', 'danger')
            return render_template('admin/users/add.html', user=user, departments=departments, roles=UserRole.CHOICES)

        # Check duplicate email
        if User.query.filter_by(email=email).first():
            flash(f"A user with email '{email}' already exists.", 'danger')
            return render_template('admin/users/add.html', user=user, departments=departments, roles=UserRole.CHOICES)

        new_user = User(
            name=name,
            email=email,
            phone=phone if phone else None,
            role=role,
            is_active=True
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()

        # Handle Profile creation by role
        if role == UserRole.STUDENT:
            roll_number = request.form.get('roll_number', '').strip().upper()
            dept = request.form.get('department', '').strip()
            year = int(request.form.get('year', 1))
            section = request.form.get('section', 'A').strip().upper()

            if not roll_number or not dept:
                db.session.rollback()
                flash('Roll Number and Department are required for students.', 'danger')
                return render_template('admin/users/add.html', user=user, departments=departments, roles=UserRole.CHOICES)

            if StudentProfile.query.filter_by(roll_number=roll_number).first():
                db.session.rollback()
                flash(f"Roll Number '{roll_number}' is already assigned to another student.", 'danger')
                return render_template('admin/users/add.html', user=user, departments=departments, roles=UserRole.CHOICES)

            sp = StudentProfile(
                user_id=new_user.id,
                roll_number=roll_number,
                department=dept,
                year=year,
                section=section
            )
            db.session.add(sp)

        elif role in (UserRole.HOD, UserRole.FACULTY, UserRole.FACULTY_ADMIN):
            emp_id = request.form.get('employee_id', '').strip().upper()
            dept = request.form.get('department', '').strip()
            designation = request.form.get('designation', '').strip() or ('Head of Department' if role == UserRole.HOD else 'Assistant Professor')

            if not emp_id or not dept:
                db.session.rollback()
                flash('Employee ID and Department are required for faculty.', 'danger')
                return render_template('admin/users/add.html', user=user, departments=departments, roles=UserRole.CHOICES)

            if FacultyProfile.query.filter_by(employee_id=emp_id).first():
                db.session.rollback()
                flash(f"Employee ID '{emp_id}' is already registered.", 'danger')
                return render_template('admin/users/add.html', user=user, departments=departments, roles=UserRole.CHOICES)

            fp = FacultyProfile(
                user_id=new_user.id,
                employee_id=emp_id,
                department=dept,
                designation=designation
            )
            db.session.add(fp)

            if role == UserRole.HOD:
                cd = CollegeDepartment.query.filter_by(code=dept).first()
                if cd:
                    cd.hod_id = new_user.id

        elif role == UserRole.ORGANIZER:
            org_name = request.form.get('organization_name', '').strip() or f"{name}'s Club"
            dept = request.form.get('department', 'General').strip()
            designation = request.form.get('designation', 'Lead Coordinator').strip()

            op = OrganizerProfile(
                user_id=new_user.id,
                organization_name=org_name,
                department=dept,
                designation=designation,
                is_verified=True,
                status='APPROVED',
                approved_by_id=user.id,
                approved_at=datetime.utcnow()
            )
            db.session.add(op)

        db.session.commit()

        log_audit_action(
            admin=user,
            action="USER_CREATED",
            target_type="User",
            target_id=new_user.id,
            target_name=new_user.name,
            details=f"Created {role} account for {new_user.email}"
        )

        flash(f"User '{new_user.name}' ({new_user.email}) successfully created with role {role}.", 'success')
        return redirect(url_for('admin.users_list'))

    return render_template('admin/users/add.html', user=user, departments=departments, roles=UserRole.CHOICES)


# View User Detail
@admin_bp.route('/users/<int:user_id>')
@super_admin_required
def user_detail(user_id):
    user = get_current_user()
    target_user = User.query.get_or_404(user_id)

    # Fetch registrations, certificates, attendance
    registrations = target_user.registrations.all() if target_user.is_student else []
    organized_events = target_user.organized_events.all() if target_user.is_organizer else []
    attendance_records = AttendanceRecord.query.filter_by(student_id=target_user.id).all() if target_user.is_student else []
    certificates = Certificate.query.filter_by(student_id=target_user.id).all() if target_user.is_student else []
    user_audit_logs = AuditLog.query.filter_by(target_id=target_user.id, target_type='User').order_by(AuditLog.created_at.desc()).limit(10).all()

    return render_template(
        'admin/users/detail.html',
        user=user,
        target_user=target_user,
        registrations=registrations,
        organized_events=organized_events,
        attendance_records=attendance_records,
        certificates=certificates,
        user_audit_logs=user_audit_logs
    )


# Edit User
@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@super_admin_required
def user_edit(user_id):
    user = get_current_user()
    target_user = User.query.get_or_404(user_id)
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        new_role = normalize_role(request.form.get('role', target_user.role))
        is_active = request.form.get('is_active') == 'on'
        new_password = request.form.get('new_password', '').strip()

        if not name or not email:
            flash('Name and Email are required.', 'danger')
            return render_template('admin/users/edit.html', user=user, target_user=target_user, departments=departments, roles=UserRole.CHOICES)

        # Duplicate email check (case-insensitive across other users)
        existing_email_user = User.query.filter(func.lower(User.email) == email.lower(), User.id != target_user.id).first()
        if existing_email_user:
            flash(f"Email '{email}' is already taken by another user.", 'danger')
            return render_template('admin/users/edit.html', user=user, target_user=target_user, departments=departments, roles=UserRole.CHOICES)

        changes = []
        if target_user.name != name:
            changes.append(f"Name: '{target_user.name}' -> '{name}'")
            target_user.name = name
        if target_user.email != email:
            changes.append(f"Email: '{target_user.email}' -> '{email}'")
            target_user.email = email
        if (target_user.phone or '') != phone:
            changes.append(f"Phone: '{target_user.phone or ''}' -> '{phone}'")
            target_user.phone = phone if phone else None
        if target_user.role != new_role:
            changes.append(f"Role: '{target_user.role}' -> '{new_role}'")
            target_user.role = new_role
        if target_user.is_active != is_active:
            changes.append(f"Status: '{'Active' if target_user.is_active else 'Inactive'}' -> '{'Active' if is_active else 'Inactive'}'")
            target_user.is_active = is_active

        # Optional new password
        if new_password:
            if len(new_password) < 6:
                flash('New password must be at least 6 characters long.', 'danger')
                return render_template('admin/users/edit.html', user=user, target_user=target_user, departments=departments, roles=UserRole.CHOICES)
            target_user.set_password(new_password)
            changes.append("Password updated")

        # Update or provision profile attributes based on target role
        if new_role == UserRole.STUDENT:
            roll = request.form.get('roll_number', '').strip().upper()
            dept = request.form.get('department', '').strip()
            year_val = request.form.get('year', '').strip()
            sec = request.form.get('section', '').strip().upper()

            if not dept:
                dept = target_user.student_profile.department if target_user.student_profile else (departments[0].code if departments else 'CSE')
            if not roll:
                roll = target_user.student_profile.roll_number if target_user.student_profile else f"STU-{target_user.id:04d}"
            if not sec:
                sec = target_user.student_profile.section if target_user.student_profile else 'A'

            try:
                year = int(year_val) if year_val else (target_user.student_profile.year if target_user.student_profile and target_user.student_profile.year else 1)
            except (ValueError, TypeError):
                year = 1

            dup_roll = StudentProfile.query.filter(StudentProfile.roll_number == roll, StudentProfile.user_id != target_user.id).first()
            if dup_roll:
                flash(f"Roll Number '{roll}' is already in use by another student.", 'danger')
                return render_template('admin/users/edit.html', user=user, target_user=target_user, departments=departments, roles=UserRole.CHOICES)

            if not target_user.student_profile:
                sp = StudentProfile(
                    user_id=target_user.id,
                    roll_number=roll,
                    department=dept,
                    year=year,
                    section=sec
                )
                db.session.add(sp)
                changes.append(f"Created StudentProfile: {roll} ({dept})")
            else:
                if target_user.student_profile.roll_number != roll:
                    changes.append(f"Roll: '{target_user.student_profile.roll_number}' -> '{roll}'")
                    target_user.student_profile.roll_number = roll
                if target_user.student_profile.department != dept:
                    changes.append(f"Dept: '{target_user.student_profile.department}' -> '{dept}'")
                    target_user.student_profile.department = dept
                target_user.student_profile.year = year
                target_user.student_profile.section = sec

        elif new_role in (UserRole.HOD, UserRole.FACULTY, UserRole.FACULTY_ADMIN, UserRole.STUDENTS_AFFAIRS_DEAN, UserRole.SUPER_ADMIN):
            empid = request.form.get('employee_id', '').strip().upper()
            dept = request.form.get('department', '').strip() or (target_user.faculty_profile.department if target_user.faculty_profile else 'General')
            desig = request.form.get('designation', '').strip()

            if not desig:
                if new_role == UserRole.STUDENTS_AFFAIRS_DEAN:
                    desig = 'Students Affairs Dean'
                elif new_role == UserRole.HOD:
                    desig = 'Head of Department & Professor'
                elif new_role == UserRole.SUPER_ADMIN:
                    desig = 'Super Administrator'
                else:
                    desig = 'Assistant Professor'

            if not empid:
                empid = target_user.faculty_profile.employee_id if target_user.faculty_profile else f"EMP-{target_user.id:04d}"

            dup_emp = FacultyProfile.query.filter(FacultyProfile.employee_id == empid, FacultyProfile.user_id != target_user.id).first()
            if dup_emp:
                flash(f"Employee ID '{empid}' is already in use by another faculty member.", 'danger')
                return render_template('admin/users/edit.html', user=user, target_user=target_user, departments=departments, roles=UserRole.CHOICES)

            if not target_user.faculty_profile:
                fp = FacultyProfile(
                    user_id=target_user.id,
                    employee_id=empid,
                    department=dept,
                    designation=desig
                )
                db.session.add(fp)
                changes.append(f"Created FacultyProfile: {empid} ({dept})")
            else:
                if target_user.faculty_profile.employee_id != empid:
                    changes.append(f"EmpID: '{target_user.faculty_profile.employee_id}' -> '{empid}'")
                    target_user.faculty_profile.employee_id = empid
                if target_user.faculty_profile.department != dept:
                    changes.append(f"Dept: '{target_user.faculty_profile.department}' -> '{dept}'")
                    target_user.faculty_profile.department = dept
                if target_user.faculty_profile.designation != desig:
                    changes.append(f"Designation: '{target_user.faculty_profile.designation}' -> '{desig}'")
                    target_user.faculty_profile.designation = desig

            if new_role == UserRole.HOD and dept and dept != 'General':
                cd = CollegeDepartment.query.filter_by(code=dept).first()
                if cd:
                    cd.hod_id = target_user.id

        elif new_role == UserRole.ORGANIZER:
            org_name = request.form.get('organization_name', '').strip() or (target_user.organizer_profile.organization_name if target_user.organizer_profile else f"{target_user.name}'s Organization")
            dept = request.form.get('department', '').strip() or (target_user.organizer_profile.department if target_user.organizer_profile else 'General')
            desig = request.form.get('designation', '').strip() or (target_user.organizer_profile.designation if target_user.organizer_profile else 'Lead Organizer')
            org_roll = request.form.get('roll_number', '').strip().upper()

            if not target_user.organizer_profile:
                op = OrganizerProfile(
                    user_id=target_user.id,
                    roll_number=org_roll or None,
                    organization_name=org_name,
                    department=dept,
                    designation=desig,
                    is_verified=True,
                    status='APPROVED',
                    approved_by_id=user.id,
                    approved_at=datetime.utcnow()
                )
                db.session.add(op)
                changes.append(f"Created OrganizerProfile: {org_name}")
            else:
                target_user.organizer_profile.organization_name = org_name
                target_user.organizer_profile.department = dept
                target_user.organizer_profile.designation = desig
                if org_roll:
                    target_user.organizer_profile.roll_number = org_roll

        db.session.commit()

        if changes:
            log_audit_action(
                admin=user,
                action="USER_EDITED",
                target_type="User",
                target_id=target_user.id,
                target_name=target_user.name,
                details="; ".join(changes)
            )

        flash(f"User '{target_user.name}' updated successfully.", 'success')
        return redirect(url_for('admin.user_detail', user_id=target_user.id))

    return render_template('admin/users/edit.html', user=user, target_user=target_user, departments=departments, roles=UserRole.CHOICES)


# Toggle User Status (Activate/Deactivate)
@admin_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@super_admin_required
def toggle_user_status(user_id):
    current_admin = get_current_user()
    target_user = User.query.get_or_404(user_id)

    if target_user.id == current_admin.id:
        flash('You cannot deactivate your own administrative account.', 'danger')
        return redirect(request.referrer or url_for('admin.users_list'))

    target_user.is_active = not target_user.is_active
    db.session.commit()

    action_label = "USER_ACTIVATED" if target_user.is_active else "USER_DEACTIVATED"
    status_str = 'activated' if target_user.is_active else 'deactivated'

    log_audit_action(
        admin=current_admin,
        action=action_label,
        target_type="User",
        target_id=target_user.id,
        target_name=target_user.name,
        details=f"User account status toggled to {status_str}."
    )

    flash(f"User '{target_user.name}' ({target_user.email}) has been {status_str}.", 'info')
    return redirect(request.referrer or url_for('admin.users_list'))


# Delete User (Safe Soft-Deactivation if FKs exist)
@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@super_admin_required
def delete_user(user_id):
    current_admin = get_current_user()
    target_user = User.query.get_or_404(user_id)

    if target_user.id == current_admin.id:
        flash('You cannot delete your own administrative account.', 'danger')
        return redirect(url_for('admin.users_list'))

    name = target_user.name
    email = target_user.email

    # Check for core participation history (registrations, organized events, student attendance, certificates, payments, teams)
    has_registrations = target_user.registrations.count() > 0
    has_events = target_user.organized_events.count() > 0
    has_attendance = AttendanceRecord.query.filter_by(student_id=target_user.id).count() > 0
    has_certificates = Certificate.query.filter_by(student_id=target_user.id).count() > 0
    has_payments = Payment.query.filter((Payment.student_id == target_user.id) | (Payment.organizer_id == target_user.id)).count() > 0
    has_teams = Team.query.filter_by(team_lead_id=target_user.id).count() > 0
    has_team_members = TeamMember.query.filter_by(student_id=target_user.id).count() > 0

    reasons = []
    if has_registrations: reasons.append("registrations")
    if has_events: reasons.append("organized events")
    if has_attendance: reasons.append("attendance records")
    if has_certificates: reasons.append("certificates")
    if has_payments: reasons.append("payments")
    if has_teams: reasons.append("led teams")
    if has_team_members: reasons.append("team memberships")

    if reasons:
        # Soft-deactivation to preserve academic and historical audit integrity
        target_user.is_active = False
        db.session.commit()

        details_msg = f"Soft-deactivated user '{name}' ({email}) because related college history exists ({', '.join(reasons)})."
        log_audit_action(
            admin=current_admin,
            action="USER_DEACTIVATED",
            target_type="User",
            target_id=target_user.id,
            target_name=name,
            details=details_msg
        )

        flash(f"User '{name}' has existing records ({', '.join(reasons)}). For data integrity, the account has been DEACTIVATED rather than erased.", 'warning')
    else:
        # Standalone user with no core event dependencies -> safely clean up references & hard delete
        try:
            # Nullify referencing columns across reviewer/approver relations
            OrganizerProfile.query.filter_by(approved_by_id=target_user.id).update({'approved_by_id': None}, synchronize_session=False)
            OrganizerRequest.query.filter_by(reviewed_by_hod_id=target_user.id).update({'reviewed_by_hod_id': None}, synchronize_session=False)
            EventRequest.query.filter_by(hod_reviewer_id=target_user.id).update({'hod_reviewer_id': None}, synchronize_session=False)
            EventRequest.query.filter_by(dean_reviewer_id=target_user.id).update({'dean_reviewer_id': None}, synchronize_session=False)
            Certificate.query.filter_by(assigned_by_id=target_user.id).update({'assigned_by_id': None}, synchronize_session=False)
            Payment.query.filter_by(verified_by_id=target_user.id).update({'verified_by_id': None}, synchronize_session=False)
            AttendanceRecord.query.filter_by(marked_by_id=target_user.id).update({'marked_by_id': None}, synchronize_session=False)
            AuditLog.query.filter_by(admin_id=target_user.id).update({'admin_id': None}, synchronize_session=False)
            CollegeDepartment.query.filter_by(hod_id=target_user.id).update({'hod_id': None}, synchronize_session=False)
            Announcement.query.filter_by(author_id=target_user.id).delete(synchronize_session=False)
            TeamInvitation.query.filter_by(invited_student_id=target_user.id).delete(synchronize_session=False)

            db.session.delete(target_user)
            db.session.commit()

            log_audit_action(
                admin=current_admin,
                action="USER_DELETED",
                target_type="User",
                target_id=user_id,
                target_name=name,
                details=f"Permanently removed user '{name}' ({email})."
            )

            flash(f"User '{name}' ({email}) has been permanently deleted.", 'success')
        except Exception as e:
            db.session.rollback()
            # Safely fall back to soft-deactivation
            fallback_user = User.query.get(user_id)
            if fallback_user:
                fallback_user.is_active = False
                db.session.commit()
                log_audit_action(
                    admin=current_admin,
                    action="USER_DEACTIVATED",
                    target_type="User",
                    target_id=user_id,
                    target_name=name,
                    details=f"Soft-deactivated user '{name}' ({email}) following delete constraint error: {str(e)}"
                )
                flash(f"User '{name}' could not be deleted due to database references. The account has been deactivated instead.", 'warning')
            else:
                flash(f"User could not be deleted: {str(e)}", 'danger')

    return redirect(url_for('admin.users_list'))


# Reset User Password
@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@super_admin_required
def reset_user_password(user_id):
    current_admin = get_current_user()
    target_user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()

    if not new_password or len(new_password) < 6:
        flash('Password must be at least 6 characters long.', 'danger')
        return redirect(request.referrer or url_for('admin.user_detail', user_id=target_user.id))

    target_user.set_password(new_password)
    db.session.commit()

    log_audit_action(
        admin=current_admin,
        action="PASSWORD_RESET",
        target_type="User",
        target_id=target_user.id,
        target_name=target_user.name,
        details=f"Password was manually reset by Super Admin {current_admin.name}."
    )

    flash(f"Password for '{target_user.name}' was successfully reset.", 'success')
    return redirect(request.referrer or url_for('admin.user_detail', user_id=target_user.id))


# Bulk Import Users (Excel / CSV)
@admin_bp.route('/users/import', methods=['GET', 'POST'])
@super_admin_required
def import_users():
    user = get_current_user()

    if request.method == 'POST':
        role = normalize_role(request.form.get('role', UserRole.STUDENT))
        default_pwd = request.form.get('default_password', 'Pass@123').strip() or 'Pass@123'
        action = request.form.get('action', 'preview')

        if 'import_file' not in request.files:
            flash('No file was uploaded.', 'danger')
            return redirect(url_for('admin.import_users'))

        uploaded_file = request.files['import_file']
        if not uploaded_file or not uploaded_file.filename:
            flash('Please select a valid CSV or Excel file to upload.', 'danger')
            return redirect(url_for('admin.import_users'))

        try:
            raw_rows = parse_file_rows(uploaded_file)
        except Exception as e:
            flash(f"Failed to parse file: {str(e)}", 'danger')
            return redirect(url_for('admin.import_users'))

        if not raw_rows:
            flash('The uploaded file contains no data rows.', 'warning')
            return redirect(url_for('admin.import_users'))

        validation_result = validate_import_data(raw_rows, role)

        if action == 'confirm':
            # Execute transactional commit
            if not validation_result['valid_rows']:
                flash('Cannot import: No valid rows found.', 'danger')
                return render_template('admin/users/import.html', user=user, validation_result=validation_result, role=role)

            success_count, err = execute_import(
                validation_result['valid_rows'],
                role=role,
                default_password=default_pwd,
                admin_user=user
            )

            if err:
                flash(f"Import failed during database insertion: {err}", 'danger')
            else:
                flash(f"Bulk Import Complete! Successfully added {success_count} {role} accounts.", 'success')
                return redirect(url_for('admin.users_list', role=role))

        return render_template('admin/users/import.html', user=user, validation_result=validation_result, role=role, default_password=default_pwd)

    return render_template('admin/users/import.html', user=user, validation_result=None, role=UserRole.STUDENT)


# Download Import Sample Template
@admin_bp.route('/users/import/template/<role>')
@super_admin_required
def download_import_template(role):
    csv_data = generate_sample_csv(role)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=campusflow_template_{role.lower()}.csv"}
    )


# ==============================================================================
# 4. DEPARTMENT MANAGEMENT (CRUD & HOD ASSIGNMENT)
# ==============================================================================
@admin_bp.route('/departments')
@super_admin_required
def departments_list():
    user = get_current_user()
    depts = CollegeDepartment.query.order_by(CollegeDepartment.id.asc()).all()

    dept_stats = []
    for d in depts:
        s_count = StudentProfile.query.filter_by(department=d.code).count()
        f_count = FacultyProfile.query.filter_by(department=d.code).count()
        e_count = Event.query.filter_by(department=d.code).count()
        dept_stats.append({
            'dept': d,
            'students_count': s_count,
            'faculty_count': f_count,
            'events_count': e_count
        })

    return render_template('admin/departments/index.html', user=user, dept_stats=dept_stats)


@admin_bp.route('/departments/add', methods=['GET', 'POST'])
@super_admin_required
def department_add():
    user = get_current_user()
    eligible_hods = User.query.filter(User.role.in_([UserRole.FACULTY, UserRole.HOD, UserRole.FACULTY_ADMIN])).all()

    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        hod_id_val = request.form.get('hod_id')
        hod_id = int(hod_id_val) if hod_id_val and hod_id_val.isdigit() else None

        if not code or not name:
            flash('Department Code and Name are required.', 'danger')
            return render_template('admin/departments/form.html', user=user, dept=None, eligible_hods=eligible_hods)

        if CollegeDepartment.query.filter_by(code=code).first():
            flash(f"A department with code '{code}' already exists.", 'danger')
            return render_template('admin/departments/form.html', user=user, dept=None, eligible_hods=eligible_hods)

        dept = CollegeDepartment(
            code=code,
            name=name,
            description=description,
            hod_id=hod_id,
            is_active=True
        )
        db.session.add(dept)
        db.session.commit()

        log_audit_action(
            admin=user,
            action="DEPARTMENT_CREATED",
            target_type="Department",
            target_id=dept.id,
            target_name=dept.code,
            details=f"Created department {dept.name} ({dept.code})"
        )

        flash(f"Department '{dept.name}' ({dept.code}) created successfully.", 'success')
        return redirect(url_for('admin.departments_list'))

    return render_template('admin/departments/form.html', user=user, dept=None, eligible_hods=eligible_hods)


@admin_bp.route('/departments/<int:dept_id>/edit', methods=['GET', 'POST'])
@super_admin_required
def department_edit(dept_id):
    user = get_current_user()
    dept = CollegeDepartment.query.get_or_404(dept_id)
    eligible_hods = User.query.filter(User.role.in_([UserRole.FACULTY, UserRole.HOD, UserRole.FACULTY_ADMIN])).all()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        hod_id_val = request.form.get('hod_id')
        hod_id = int(hod_id_val) if hod_id_val and hod_id_val.isdigit() else None
        is_active = request.form.get('is_active') == 'on'

        if not name:
            flash('Department Name is required.', 'danger')
            return render_template('admin/departments/form.html', user=user, dept=dept, eligible_hods=eligible_hods)

        dept.name = name
        dept.description = description
        dept.hod_id = hod_id
        dept.is_active = is_active
        dept.updated_at = datetime.utcnow()
        db.session.commit()

        log_audit_action(
            admin=user,
            action="DEPARTMENT_MODIFIED",
            target_type="Department",
            target_id=dept.id,
            target_name=dept.code,
            details=f"Updated department {dept.name} ({dept.code}), HOD id={hod_id}"
        )

        flash(f"Department '{dept.code}' updated successfully.", 'success')
        return redirect(url_for('admin.departments_list'))

    return render_template('admin/departments/form.html', user=user, dept=dept, eligible_hods=eligible_hods)


@admin_bp.route('/departments/<int:dept_id>/toggle-status', methods=['POST'])
@super_admin_required
def department_toggle_status(dept_id):
    user = get_current_user()
    dept = CollegeDepartment.query.get_or_404(dept_id)
    dept.is_active = not dept.is_active
    db.session.commit()

    status_str = "activated" if dept.is_active else "deactivated"
    log_audit_action(
        admin=user,
        action="DEPARTMENT_MODIFIED",
        target_type="Department",
        target_id=dept.id,
        target_name=dept.code,
        details=f"Department {dept.code} {status_str}."
    )

    flash(f"Department '{dept.code}' has been {status_str}.", 'info')
    return redirect(url_for('admin.departments_list'))


@admin_bp.route('/departments/<int:dept_id>')
@super_admin_required
def department_detail(dept_id):
    user = get_current_user()
    dept = CollegeDepartment.query.get_or_404(dept_id)

    students = StudentProfile.query.filter_by(department=dept.code).all()
    faculty = FacultyProfile.query.filter_by(department=dept.code).all()
    events = Event.query.filter_by(department=dept.code).order_by(Event.created_at.desc()).all()

    return render_template(
        'admin/departments/detail.html',
        user=user,
        dept=dept,
        students=students,
        faculty=faculty,
        events=events
    )


# ==============================================================================
# 5. EVENT MANAGEMENT
# ==============================================================================
@admin_bp.route('/events')
@super_admin_required
def events_list():
    user = get_current_user()
    status_filter = request.args.get('status', 'ALL').strip()
    dept_filter = request.args.get('dept', 'ALL').strip()
    search = request.args.get('q', '').strip()

    query = Event.query

    if status_filter and status_filter != 'ALL':
        query = query.filter_by(status=status_filter)

    if dept_filter and dept_filter != 'ALL':
        query = query.filter_by(department=dept_filter)

    if search:
        query = query.filter(
            or_(
                Event.title.ilike(f'%{search}%'),
                Event.venue.ilike(f'%{search}%'),
                Event.department.ilike(f'%{search}%')
            )
        )

    events = query.order_by(Event.created_at.desc()).all()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    return render_template(
        'admin/events/index.html',
        user=user,
        events=events,
        status_filter=status_filter,
        dept_filter=dept_filter,
        search=search,
        departments=departments,
        event_statuses=EventStatus.CHOICES
    )


@admin_bp.route('/events/<int:event_id>')
@super_admin_required
def event_detail(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    registrations = event.registrations.all() if hasattr(event.registrations, 'all') else event.registrations
    attendance_records = event.attendance_records if isinstance(event.attendance_records, list) else event.attendance_records.all()
    revenue = sum([(r.payment.amount or 0.0) for r in registrations if r.payment and r.payment.status in (PaymentStatus.VERIFIED, 'SUCCESS')])
    certificates = Certificate.query.filter_by(event_id=event.id).all()

    return render_template(
        'admin/events/detail.html',
        user=user,
        event=event,
        registrations=registrations,
        attendance_records=attendance_records,
        revenue=revenue,
        certificates=certificates
    )


@admin_bp.route('/events/<int:event_id>/edit', methods=['GET', 'POST'])
@super_admin_required
def event_edit(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        event.title = title or event.title
        event.department = request.form.get('department', event.department).strip()
        event.venue = request.form.get('venue', event.venue).strip()
        event.description = request.form.get('description', event.description).strip()
        event.status = request.form.get('status', event.status)
        event.max_participants = int(request.form.get('max_participants', event.max_participants))
        event.registration_fee = float(request.form.get('registration_fee', event.registration_fee))
        event.is_free = request.form.get('is_free') == 'on'
        if event.is_free:
            event.registration_fee = 0.0

        db.session.commit()

        log_audit_action(
            admin=user,
            action="EVENT_MODIFIED",
            target_type="Event",
            target_id=event.id,
            target_name=event.title,
            details=f"Super Admin updated event details, status={event.status}"
        )

        flash(f"Event '{event.title}' updated successfully.", 'success')
        return redirect(url_for('admin.event_detail', event_id=event.id))

    return render_template('admin/events/edit.html', user=user, event=event, departments=departments, statuses=EventStatus.CHOICES)


@admin_bp.route('/events/<int:event_id>/action', methods=['POST'])
@super_admin_required
def event_action(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)
    action = request.form.get('action')
    rejection_reason = request.form.get('rejection_reason', '').strip()

    if action == 'approve':
        event.status = EventStatus.APPROVED
        event.rejection_reason = None
        flash(f"Event '{event.title}' approved successfully.", 'success')
    elif action == 'reject':
        event.status = EventStatus.REJECTED
        event.rejection_reason = rejection_reason or "Does not meet college criteria."
        flash(f"Event '{event.title}' has been rejected.", 'warning')
    elif action == 'cancel':
        event.status = EventStatus.CANCELLED
        flash(f"Event '{event.title}' cancelled.", 'danger')
    elif action == 'complete':
        event.status = EventStatus.EVENT_COMPLETED
        flash(f"Event '{event.title}' marked as completed.", 'info')

    db.session.commit()

    # Dispatch in-app notification and email to organizer
    try:
        from services.notification_service import create_notification
        from models.notification import NotificationType
        from services.email_service import send_event_admin_action_email
        if event.organizer_id:
            create_notification(
                user_id=event.organizer_id,
                title=f"Event Status: {action.upper()}",
                message=f"Your event '{event.title}' status was updated to {action.upper()} by Administrator {user.name}.",
                notification_type=NotificationType.SYSTEM,
                link=url_for('organizer.manage_event', event_id=event.id) if event.id else url_for('organizer.dashboard')
            )
            if event.organizer:
                send_event_admin_action_email(event, event.organizer, action.upper(), reason=rejection_reason)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch event admin action notification/email: {exc}")

    log_audit_action(
        admin=user,
        action="EVENT_MODIFIED",
        target_type="Event",
        target_id=event.id,
        target_name=event.title,
        details=f"Event action executed: {action}"
    )

    return redirect(request.referrer or url_for('admin.events_list'))


@admin_bp.route('/events/<int:event_id>/delete', methods=['POST'])
@super_admin_required
def delete_event(event_id):
    user = get_current_user()
    event = Event.query.get_or_404(event_id)

    title = event.title
    delete_event_with_cleanup(event)
    db.session.commit()

    log_audit_action(
        admin=user,
        action="EVENT_DELETED",
        target_type="Event",
        target_id=event_id,
        target_name=title,
        details=f"Super Admin permanently deleted event '{title}' and cleaned associated records."
    )

    flash(f"Event '{title}' and associated records were permanently deleted.", 'success')
    return redirect(url_for('admin.events_list'))


@admin_bp.route('/events/delete-expired', methods=['POST'])
@super_admin_required
def delete_expired():
    admin_user = get_current_user()
    now = datetime.utcnow()
    count, deleted_titles, skipped_titles = delete_expired_events(now, require_certificates_done=True)
    if count > 0:
        log_audit_action(
            admin=admin_user,
            action="EVENTS_DELETED_EXPIRED",
            target_type="Event",
            target_id=0,
            target_name=f"{count} expired events",
            details=f"Deleted expired events: {', '.join(deleted_titles)}"
        )
        flash(f"Successfully deleted {count} expired event(s) whose certificates were issued.", 'success')
    else:
        flash("No eligible expired events found for deletion.", 'info')

    if skipped_titles:
        flash(f"Skipped {len(skipped_titles)} event(s) because certificate issuance is pending: {', '.join(skipped_titles)}", 'warning')

    return redirect(url_for('admin.events_list'))


# Organizer Approval Actions
@admin_bp.route('/organizers/<int:organizer_profile_id>/action', methods=['POST'])
@super_admin_required
def organizer_action(organizer_profile_id):
    current_admin = get_current_user()
    org_profile = OrganizerProfile.query.get_or_404(organizer_profile_id)
    action = request.form.get('action')
    rejection_reason = request.form.get('rejection_reason', '').strip()

    if action == 'approve':
        org_profile.is_verified = True
        org_profile.status = 'APPROVED'
        org_profile.approved_by_id = current_admin.id
        org_profile.approved_at = datetime.utcnow()
        org_profile.rejection_reason = None
        org_profile.user.is_active = True
        flash(f"Organizer '{org_profile.organization_name}' approved.", 'success')
    elif action == 'reject':
        org_profile.is_verified = False
        org_profile.status = 'REJECTED'
        org_profile.rejection_reason = rejection_reason or "Registration does not meet approval criteria."
        flash(f"Organizer '{org_profile.organization_name}' rejected.", 'warning')

    db.session.commit()

    # Dispatch in-app notification and email to organizer user
    try:
        from services.notification_service import create_notification
        from models.notification import NotificationType
        from services.email_service import send_organizer_request_approved_email, send_organizer_request_rejected_email
        if org_profile.user:
            if action == 'approve':
                create_notification(
                    user_id=org_profile.user.id,
                    title="Organizer Application Approved",
                    message=f"Congratulations! Your organizer account for '{org_profile.organization_name}' has been APPROVED by Super Admin {current_admin.name}.",
                    notification_type=NotificationType.ORGANIZER_APPROVAL,
                    link=url_for('organizer.dashboard')
                )
                send_organizer_request_approved_email(None, org_profile.user, current_admin)
            elif action == 'reject':
                create_notification(
                    user_id=org_profile.user.id,
                    title="Organizer Application Rejected",
                    message=f"Your organizer application was rejected by Super Admin {current_admin.name}. Reason: {org_profile.rejection_reason}",
                    notification_type=NotificationType.ORGANIZER_REJECTION,
                    link=url_for('student.dashboard')
                )
                send_organizer_request_rejected_email(None, org_profile.user, current_admin, reason=org_profile.rejection_reason)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch admin organizer action notification/email: {exc}")

    log_audit_action(
        admin=current_admin,
        action="ORGANIZER_ACTION",
        target_type="OrganizerProfile",
        target_id=org_profile.id,
        target_name=org_profile.organization_name,
        details=f"Organizer application status updated to {action}."
    )

    return redirect(request.referrer or url_for('admin.users_list', role='ORGANIZER'))


# ==============================================================================
# 6. REGISTRATION MANAGEMENT
# ==============================================================================
@admin_bp.route('/registrations')
@super_admin_required
def registrations_list():
    user = get_current_user()
    event_filter = request.args.get('event_id', type=int)
    dept_filter = request.args.get('dept', 'ALL').strip()
    payment_filter = request.args.get('payment_status', 'ALL').strip()
    status_filter = request.args.get('status', 'ALL').strip()
    page = request.args.get('page', 1, type=int)

    query = EventRegistration.query.join(User, EventRegistration.student_id == User.id).join(Event, EventRegistration.event_id == Event.id).outerjoin(StudentProfile, User.id == StudentProfile.user_id).outerjoin(Payment, EventRegistration.id == Payment.registration_id)

    if event_filter:
        query = query.filter(EventRegistration.event_id == event_filter)

    if dept_filter and dept_filter != 'ALL':
        query = query.filter(StudentProfile.department == dept_filter)

    if status_filter and status_filter != 'ALL':
        query = query.filter(EventRegistration.status == status_filter)

    if payment_filter and payment_filter != 'ALL':
        if payment_filter == 'FREE':
            query = query.filter(Event.is_free.is_(True))
        else:
            query = query.filter(Payment.status == payment_filter)

    pagination = query.order_by(EventRegistration.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    registrations = pagination.items

    events = Event.query.order_by(Event.title.asc()).all()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    return render_template(
        'admin/registrations/index.html',
        user=user,
        registrations=registrations,
        pagination=pagination,
        events=events,
        departments=departments,
        event_filter=event_filter,
        dept_filter=dept_filter,
        payment_filter=payment_filter,
        status_filter=status_filter
    )


# ==============================================================================
# 7. PAYMENT MANAGEMENT (READ-ONLY INSPECTION)
# ==============================================================================
@admin_bp.route('/payments')
@super_admin_required
def payments_list():
    user = get_current_user()
    status_filter = request.args.get('status', 'ALL').strip()
    event_filter = request.args.get('event_id', type=int)
    page = request.args.get('page', 1, type=int)

    query = Payment.query.join(Event, Payment.event_id == Event.id).join(User, Payment.student_id == User.id)

    if status_filter and status_filter != 'ALL':
        query = query.filter(Payment.status == status_filter)

    if event_filter:
        query = query.filter(Payment.event_id == event_filter)

    pagination = query.order_by(Payment.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    payments = pagination.items

    total_amount = db.session.query(func.sum(Payment.amount)).filter(Payment.status.in_([PaymentStatus.VERIFIED, 'SUCCESS'])).scalar() or 0.0
    events = Event.query.order_by(Event.title.asc()).all()

    return render_template(
        'admin/payments/index.html',
        user=user,
        payments=payments,
        pagination=pagination,
        events=events,
        status_filter=status_filter,
        event_filter=event_filter,
        total_amount=total_amount,
        payment_statuses=PaymentStatus.CHOICES
    )


# ==============================================================================
# 8. ATTENDANCE MANAGEMENT (INSPECTION & AUDITED MANUAL CORRECTION)
# ==============================================================================
@admin_bp.route('/attendance')
@super_admin_required
def attendance_list():
    user = get_current_user()
    event_filter = request.args.get('event_id', type=int)
    status_filter = request.args.get('status', 'ALL').strip()
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = AttendanceRecord.query.join(Event, AttendanceRecord.event_id == Event.id).join(User, AttendanceRecord.student_id == User.id).outerjoin(StudentProfile, User.id == StudentProfile.user_id)

    if event_filter:
        query = query.filter(AttendanceRecord.event_id == event_filter)

    if status_filter and status_filter != 'ALL':
        query = query.filter(AttendanceRecord.status == status_filter)

    if search:
        query = query.filter(
            or_(
                User.name.ilike(f'%{search}%'),
                StudentProfile.roll_number.ilike(f'%{search}%')
            )
        )

    pagination = query.order_by(AttendanceRecord.scanned_at.desc()).paginate(page=page, per_page=25, error_out=False)
    records = pagination.items

    events = Event.query.order_by(Event.title.asc()).all()

    return render_template(
        'admin/attendance/index.html',
        user=user,
        records=records,
        pagination=pagination,
        events=events,
        event_filter=event_filter,
        status_filter=status_filter,
        search=search,
        attendance_statuses=AttendanceStatus.CHOICES
    )


@admin_bp.route('/attendance/<int:att_id>/correct', methods=['POST'])
@super_admin_required
def attendance_correct(att_id):
    current_admin = get_current_user()
    record = AttendanceRecord.query.get_or_404(att_id)
    new_status = request.form.get('status', record.status)
    remarks = request.form.get('remarks', '').strip()

    if not remarks:
        flash('Correction requires documenting a valid administrative reason in the remarks field.', 'danger')
        return redirect(request.referrer or url_for('admin.attendance_list'))

    old_status = record.status
    record.status = new_status
    record.remarks = f"[Corrected by Admin {current_admin.name}]: {remarks}"
    record.marked_by_id = current_admin.id
    db.session.commit()

    log_audit_action(
        admin=current_admin,
        action="ATTENDANCE_CORRECTED",
        target_type="AttendanceRecord",
        target_id=record.id,
        target_name=f"Student ID: {record.student_id}, Event: {record.event.title}",
        details=f"Attendance status changed from {old_status} to {new_status}. Remarks: {remarks}"
    )

    flash(f"Attendance record for student successfully updated to '{new_status}'.", 'success')
    return redirect(request.referrer or url_for('admin.attendance_list'))


# ==============================================================================
# 9. CERTIFICATE MANAGEMENT
# ==============================================================================
@admin_bp.route('/certificates')
@super_admin_required
def certificates_list():
    user = get_current_user()
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'ALL').strip()
    event_filter = request.args.get('event_id', type=int)
    page = request.args.get('page', 1, type=int)

    query = Certificate.query.join(Event, Certificate.event_id == Event.id).outerjoin(User, Certificate.student_id == User.id)

    if event_filter:
        query = query.filter(Certificate.event_id == event_filter)

    if status_filter and status_filter != 'ALL':
        query = query.filter(Certificate.status == status_filter)

    if search:
        query = query.filter(
            or_(
                Certificate.certificate_code.ilike(f'%{search}%'),
                Certificate.roll_number.ilike(f'%{search}%'),
                User.name.ilike(f'%{search}%')
            )
        )

    pagination = query.order_by(Certificate.upload_date.desc()).paginate(page=page, per_page=25, error_out=False)
    certificates = pagination.items

    events = Event.query.order_by(Event.title.asc()).all()

    return render_template(
        'admin/certificates/index.html',
        user=user,
        certificates=certificates,
        pagination=pagination,
        events=events,
        search=search,
        status_filter=status_filter,
        event_filter=event_filter,
        certificate_statuses=CertificateStatus.CHOICES
    )


@admin_bp.route('/certificates/<int:cert_id>/reissue', methods=['POST'])
@super_admin_required
def certificate_reissue(cert_id):
    current_admin = get_current_user()
    cert = Certificate.query.get_or_404(cert_id)

    student = cert.student
    event = cert.event

    if not student or not event:
        flash('Cannot reissue certificate without attached student and event records.', 'danger')
        return redirect(request.referrer or url_for('admin.certificates_list'))

    # Re-generate certificate image reusing existing code
    img_path = generate_certificate_image(
        student_name=student.name,
        roll_number=cert.roll_number or (student.student_profile.roll_number if student.student_profile else "N/A"),
        department=student.student_profile.department if student.student_profile else "General",
        event_title=event.title,
        event_date_str=event.start_time.strftime('%B %d, %Y') if event.start_time else datetime.utcnow().strftime('%B %d, %Y'),
        certificate_code=cert.certificate_code
    )

    cert.file_path = img_path
    cert.upload_date = datetime.utcnow()
    cert.assigned_by_id = current_admin.id
    db.session.commit()

    log_audit_action(
        admin=current_admin,
        action="CERTIFICATE_REISSUED",
        target_type="Certificate",
        target_id=cert.id,
        target_name=cert.certificate_code,
        details=f"Certificate {cert.certificate_code} reissued for student {student.name} ({cert.roll_number})."
    )

    flash(f"Certificate '{cert.certificate_code}' successfully regenerated and reissued.", 'success')
    return redirect(request.referrer or url_for('admin.certificates_list'))


# ==============================================================================
# 10. ANNOUNCEMENTS MANAGEMENT
# ==============================================================================
@admin_bp.route('/announcements')
@super_admin_required
def announcements_list():
    user = get_current_user()
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    return render_template(
        'admin/announcements/index.html',
        user=user,
        announcements=announcements,
        departments=departments
    )
@admin_bp.route('/announcements/create', methods=['GET', 'POST'])
@super_admin_required
def announcement_create():
    user = get_current_user()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        target_audience = request.form.get('target_audience', TargetAudience.ALL).strip().upper()
        target_dept = request.form.get('target_department', '').strip() or None
        is_pinned = request.form.get('is_pinned') == 'on'

        if not title or not message:
            flash('Title and Message content are required.', 'danger')
            return render_template('admin/announcements/form.html', user=user, ann=None, departments=departments, audiences=TargetAudience.CHOICES)

        ann = Announcement(
            author_id=user.id,
            title=title,
            message=message,
            target_audience=target_audience,
            target_department=target_dept if target_audience == TargetAudience.DEPARTMENT else None,
            is_pinned=is_pinned,
            is_active=True,
            created_at=datetime.utcnow()
        )
        db.session.add(ann)
        db.session.commit()

        log_audit_action(
            admin=user,
            action="ANNOUNCEMENT_CREATED",
            target_type="Announcement",
            target_id=ann.id,
            target_name=ann.title,
            details=f"Published announcement to target audience: {target_audience}"
        )

        flash(f"Announcement '{ann.title}' published successfully.", 'success')
        return redirect(url_for('admin.announcements_list'))

    return render_template('admin/announcements/form.html', user=user, ann=None, departments=departments, audiences=TargetAudience.CHOICES)


@admin_bp.route('/announcements/<int:ann_id>/edit', methods=['GET', 'POST'])
@super_admin_required
def announcement_edit(ann_id):
    user = get_current_user()
    ann = Announcement.query.get_or_404(ann_id)
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        target_audience = request.form.get('target_audience', ann.target_audience).strip().upper()
        target_dept = request.form.get('target_department', '').strip() or None
        is_pinned = request.form.get('is_pinned') == 'on'
        is_active = request.form.get('is_active') == 'on'

        if not title or not message:
            flash('Title and Message are required.', 'danger')
            return render_template('admin/announcements/form.html', user=user, ann=ann, departments=departments, audiences=TargetAudience.CHOICES)

        ann.title = title
        ann.message = message
        ann.target_audience = target_audience
        ann.target_department = target_dept if target_audience == TargetAudience.DEPARTMENT else None
        ann.is_pinned = is_pinned
        ann.is_active = is_active
        db.session.commit()

        log_audit_action(
            admin=user,
            action="ANNOUNCEMENT_MODIFIED",
            target_type="Announcement",
            target_id=ann.id,
            target_name=ann.title,
            details=f"Updated announcement, active={is_active}, audience={target_audience}"
        )

        flash(f"Announcement '{ann.title}' updated.", 'success')
        return redirect(url_for('admin.announcements_list'))

    return render_template('admin/announcements/form.html', user=user, ann=ann, departments=departments, audiences=TargetAudience.CHOICES)


@admin_bp.route('/announcements/<int:ann_id>/delete', methods=['POST'])
@super_admin_required
def announcement_delete(ann_id):
    user = get_current_user()
    ann = Announcement.query.get_or_404(ann_id)
    title = ann.title

    db.session.delete(ann)
    db.session.commit()

    log_audit_action(
        admin=user,
        action="ANNOUNCEMENT_DELETED",
        target_type="Announcement",
        target_id=ann_id,
        target_name=title,
        details=f"Removed announcement '{title}'"
    )

    flash(f"Announcement '{title}' deleted.", 'success')
    return redirect(url_for('admin.announcements_list'))


@admin_bp.route('/announcements/<int:ann_id>/toggle-publish', methods=['POST'])
@super_admin_required
def announcement_toggle_publish(ann_id):
    user = get_current_user()
    ann = Announcement.query.get_or_404(ann_id)
    ann.is_active = not ann.is_active
    db.session.commit()

    status_str = "published" if ann.is_active else "unpublished"
    flash(f"Announcement '{ann.title}' {status_str}.", 'info')
    return redirect(url_for('admin.announcements_list'))


# ==============================================================================
# 11. AUDIT LOGS
# ==============================================================================
@admin_bp.route('/audit-logs')
@super_admin_required
def audit_logs_list():
    user = get_current_user()
    action_filter = request.args.get('action', 'ALL').strip().upper()
    target_filter = request.args.get('target', 'ALL').strip()
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = AuditLog.query.outerjoin(User, AuditLog.admin_id == User.id)

    if action_filter and action_filter != 'ALL':
        query = query.filter(AuditLog.action == action_filter)

    if target_filter and target_filter != 'ALL':
        query = query.filter(AuditLog.target_type == target_filter)

    if search:
        query = query.filter(
            or_(
                AuditLog.target_name.ilike(f'%{search}%'),
                AuditLog.details.ilike(f'%{search}%'),
                User.name.ilike(f'%{search}%')
            )
        )

    pagination = query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=30, error_out=False)
    logs = pagination.items

    distinct_actions = [row[0] for row in db.session.query(AuditLog.action).distinct().all()]

    return render_template(
        'admin/audit_logs/index.html',
        user=user,
        logs=logs,
        pagination=pagination,
        action_filter=action_filter,
        target_filter=target_filter,
        search=search,
        distinct_actions=distinct_actions
    )


# ==============================================================================
# 12. SYSTEM SETTINGS & DIAGNOSTICS
# ==============================================================================
@admin_bp.route('/settings')
@super_admin_required
def settings_view():
    user = get_current_user()
    db_info = get_safe_db_info()
    deans = User.query.filter_by(role=UserRole.STUDENTS_AFFAIRS_DEAN).all()
    all_users = User.query.filter_by(is_active=True).order_by(User.name.asc()).all()
    from services.email_service import get_mail_config
    mail_cfg = get_mail_config()

    return render_template(
        'admin/settings/index.html',
        user=user,
        db_info=db_info,
        deans=deans,
        all_users=all_users,
        mail_cfg=mail_cfg
    )


@admin_bp.route('/test-email', methods=['POST'])
@super_admin_required
def test_email():
    user = get_current_user()
    target_email = request.form.get('recipient_email', '').strip() or user.email

    from services.email_service import test_smtp_connection, dispatch_email, get_mail_config
    cfg = get_mail_config()

    if not cfg.get('MAIL_USERNAME') or not cfg.get('MAIL_PASSWORD'):
        flash(
            "Live email credentials are not configured! Please configure MAIL_USERNAME and MAIL_PASSWORD in your hosting dashboard (e.g. Render Environment Variables).",
            "danger"
        )
        return redirect(url_for('admin.settings_view'))

    conn_success, conn_msg = test_smtp_connection(cfg)
    if not conn_success:
        flash(f"SMTP Connection Failed: {conn_msg}", "danger")
        return redirect(url_for('admin.settings_view'))

    subject = "Campus Flow - Live Email Delivery Verification"
    body_text = (
        f"Hello {user.name},\n\n"
        f"This is a live test email dispatched from Campus Flow Settings.\n\n"
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"SMTP Server: {cfg.get('MAIL_SERVER')}:{cfg.get('MAIL_PORT')}\n"
        f"Sender: {cfg.get('MAIL_DEFAULT_SENDER')}\n"
        f"Recipient: {target_email}\n\n"
        f"If you received this message, your production email system is 100% operational!\n\n"
        f"— Campus Flow System"
    )

    dispatched = dispatch_email(target_email, subject, body_text, sync=True)
    if dispatched:
        flash(f"Live test email successfully dispatched to '{target_email}'! Check your inbox.", "success")
    else:
        flash(f"SMTP connected, but message transmission to '{target_email}' failed. Check server logs.", "danger")

    return redirect(url_for('admin.settings_view'))


# ==============================================================================
# 13. SUPER ADMIN - ORGANIZER REQUESTS & EVENT PROPOSALS (COLLEGE-WIDE)
# ==============================================================================
@admin_bp.route('/organizer-requests')
@super_admin_required
def organizer_requests_list():
    user = get_current_user()
    status_filter = request.args.get('status', '').strip()
    dept_filter = request.args.get('department', '').strip()
    search = request.args.get('q', '').strip()

    query = OrganizerRequest.query.join(User, OrganizerRequest.student_id == User.id)

    if status_filter and status_filter != 'ALL':
        query = query.filter(OrganizerRequest.status == status_filter)

    if dept_filter and dept_filter != 'ALL':
        query = query.filter(OrganizerRequest.department_id == int(dept_filter))

    if search:
        query = query.filter(
            or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%"),
                OrganizerRequest.reason.ilike(f"%{search}%")
            )
        )

    requests_list = query.order_by(OrganizerRequest.created_at.desc()).all()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    return render_template(
        'admin/organizer_requests.html',
        user=user,
        requests=requests_list,
        departments=departments,
        status_filter=status_filter,
        dept_filter=dept_filter,
        search=search,
        statuses=OrganizerRequestStatus.CHOICES
    )


@admin_bp.route('/event-requests')
@super_admin_required
def event_requests_list():
    user = get_current_user()
    status_filter = request.args.get('status', '').strip()
    dept_filter = request.args.get('department', '').strip()
    search = request.args.get('q', '').strip()

    query = EventRequest.query.join(User, EventRequest.organizer_id == User.id)

    if status_filter and status_filter != 'ALL':
        query = query.filter(EventRequest.overall_status == status_filter)

    if dept_filter and dept_filter != 'ALL':
        query = query.filter(EventRequest.department_id == int(dept_filter))

    if search:
        query = query.filter(
            or_(
                EventRequest.event_name.ilike(f"%{search}%"),
                EventRequest.venue.ilike(f"%{search}%"),
                User.name.ilike(f"%{search}%")
            )
        )

    requests_list = query.order_by(EventRequest.created_at.desc()).all()
    departments = CollegeDepartment.query.filter_by(is_active=True).all()

    return render_template(
        'admin/event_requests.html',
        user=user,
        requests=requests_list,
        departments=departments,
        status_filter=status_filter,
        dept_filter=dept_filter,
        search=search,
        statuses=EventRequestStatus.CHOICES
    )


@admin_bp.route('/assign-dean', methods=['POST'])
@super_admin_required
def assign_dean():
    user = get_current_user()
    user_id_val = request.form.get('user_id')
    if not user_id_val or not user_id_val.isdigit():
        flash('Please select a valid user to assign as Students Affairs Dean.', 'danger')
        return redirect(url_for('admin.settings_view'))

    target_user = User.query.get_or_404(int(user_id_val))
    target_user.role = UserRole.STUDENTS_AFFAIRS_DEAN
    db.session.commit()

    log_audit_action(
        admin=user,
        action="ROLE_ASSIGNED",
        target_type="User",
        target_id=target_user.id,
        target_name=target_user.name,
        details=f"Assigned {target_user.name} ({target_user.email}) as Students Affairs Dean."
    )

    flash(f"User '{target_user.name}' ({target_user.email}) successfully designated as Students Affairs Dean.", 'success')
    return redirect(url_for('admin.settings_view'))
