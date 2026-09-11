import os
import unittest
import json
import uuid
from app import create_app
from config import Config
from models import (
    db, User, UserRole, FacultyProfile, StudentProfile, Event,
    OrganizerProfile, EventRegistration, RegistrationStatus,
    AttendanceRecord, Certificate, CertificateStatus, PaymentStatus, EventStatus
)

class CampusFlowTestConfig(Config):
    TESTING = True
    # Test DB URI configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or os.environ.get('DATABASE_URL') or 'sqlite:///:memory:'


class CampusFlowSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db_url = CampusFlowTestConfig.SQLALCHEMY_DATABASE_URI
        if db_url.startswith('mssql') or db_url.startswith('sqlserver'):
            try:
                import pyodbc
                conn_str = (
                    "Driver={ODBC Driver 18 for SQL Server};"
                    "Server=localhost;"
                    "Database=campus_flow;"
                    "Trusted_Connection=yes;"
                    "TrustServerCertificate=yes;"
                )
                conn = pyodbc.connect(conn_str)
                conn.close()
            except Exception:
                CampusFlowTestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
        elif db_url.startswith('mysql://') or db_url.startswith('mysql+pymysql://'):
            try:
                import pymysql
                # Fallback to local SQLite if MySQL isn't reachable
                CampusFlowTestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
            except Exception:
                CampusFlowTestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'

    def setUp(self):
        self.app = create_app(CampusFlowTestConfig)
        self.app.config['TESTING'] = True
        with self.app.app_context():
            db.create_all()

    def test_00_health_check(self):
        """Verify /health endpoint returns 200 and healthy status."""
        client = self.app.test_client()
        res = client.get('/health')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get('status'), 'healthy')

    def test_01_public_pages(self):
        """Verify home, event list, and event detail pages load properly."""
        client = self.app.test_client()
        with self.app.app_context():
            res = client.get('/')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'Campus Flow', res.data)

            res = client.get('/events')
            self.assertEqual(res.status_code, 200)

            event = Event.query.first()
            if event:
                res = client.get(f'/events/{event.slug}')
                self.assertEqual(res.status_code, 200)
                self.assertIn(event.title.encode('utf-8'), res.data)

    def test_02_error_pages(self):
        """Verify custom 404 and 400 error handlers."""
        client = self.app.test_client()
        res = client.get('/nonexistent-page-url-12345')
        self.assertEqual(res.status_code, 404)
        self.assertIn(b'Page Not Found', res.data)
        self.assertIn(b'Campus Flow', res.data)

    def test_03_organizer_registration_and_department_admin_approval(self):
        """Verify new organizer starts unapproved and requires department admin approval."""
        unique_id = uuid.uuid4().hex[:6]
        test_email = f"test.mech.{unique_id}@college.edu"

        with self.app.app_context():
            client = self.app.test_client()

            # 1. Register new organizer in MECH department
            test_roll_number = f"MECH{unique_id.upper()}"
            reg_res = client.post('/auth/register/organizer', data={
                'name': 'Test MECH Organizer',
                'email': test_email,
                'roll_number': test_roll_number,
                'organization_name': f'Automotive Society {unique_id}',
                'department': 'MECH',
                'designation': 'President',
                'phone': '+91 9988776655',
                'password': 'Pass@123',
                'confirm_password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(reg_res.status_code, 200)

            # 2. Try to log in before approval -> Should be prevented
            login_fail = client.post('/auth/login', data={
                'identifier': test_roll_number,
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(login_fail.status_code, 200)
            self.assertIn(b'pending approval', login_fail.data)

            # 3. Create or find MECH Faculty Admin
            mech_admin = User.query.filter_by(role=UserRole.FACULTY_ADMIN).first()
            if not mech_admin:
                mech_admin = User(
                    name="Dr. MECH Admin",
                    email="admin.mech@college.edu",
                    role=UserRole.FACULTY_ADMIN,
                    is_active=True
                )
                mech_admin.set_password("Pass@123")
                db.session.add(mech_admin)
                db.session.flush()
                fp = FacultyProfile(
                    user_id=mech_admin.id,
                    department="MECH",
                    employee_id="FAC-MECH-01",
                    designation="Head of Department"
                )
                db.session.add(fp)
                db.session.commit()

            admin_user = User.query.filter_by(role=UserRole.SUPER_ADMIN).first()
            if not admin_user:
                admin_user = User.query.filter_by(email="superadmin@college.edu").first()

            admin_client = self.app.test_client()
            admin_client.post('/auth/login', data={
                'email': admin_user.email if admin_user else 'superadmin@college.edu',
                'password': 'Admin@123'
            }, follow_redirects=True)

            org_user = User.query.filter_by(email=test_email).first()
            self.assertIsNotNone(org_user)
            org_prof = org_user.organizer_profile
            self.assertIsNotNone(org_prof)

            approve_res = admin_client.post(f'/admin/organizers/{org_prof.id}/action', data={
                'action': 'approve'
            }, follow_redirects=True)
            self.assertEqual(approve_res.status_code, 200)

            # 4. Now the organizer logs in successfully using roll number
            org_client = self.app.test_client()
            login_success = org_client.post('/auth/login', data={
                'identifier': test_roll_number,
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(login_success.status_code, 200)
            self.assertIn(b'Organizer Portal', login_success.data)

            # 5. Email login should fail for organizer
            fresh_client = self.app.test_client()
            email_login = fresh_client.post('/auth/login', data={
                'identifier': test_email,
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertIn(b'Invalid email or password credentials', email_login.data)

    def test_04_student_auth_and_registration(self):
        """Verify student login and event registration flow."""
        client = self.app.test_client()
        with self.app.app_context():
            student = User.query.filter_by(role=UserRole.STUDENT).first()
            if not student:
                student = User(
                    name="Campus Student",
                    email=f"student_{uuid.uuid4().hex[:6]}@college.edu",
                    role=UserRole.STUDENT,
                    is_active=True
                )
                student.set_password("Pass@123")
                db.session.add(student)
                db.session.flush()
                sp = StudentProfile(
                    user_id=student.id,
                    roll_number=f"23CS{uuid.uuid4().hex[:4].upper()}",
                    department="CSE",
                    year=3,
                    section="A"
                )
                db.session.add(sp)
                db.session.commit()

            # Student login with email should fail
            email_client = self.app.test_client()
            email_fail = email_client.post('/auth/login', data={
                'identifier': student.email,
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertIn(b'Invalid email or password credentials', email_fail.data)

            # Student logs in with roll number
            login_res = client.post('/auth/login', data={
                'identifier': student.student_profile.roll_number,
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(login_res.status_code, 200)

            event = Event.query.filter_by(status=EventStatus.APPROVED).first()
            if not event:
                org = User.query.filter_by(role=UserRole.ORGANIZER).first() or student
                event = Event(
                    title='Campus Flow Inaugural Workshop',
                    slug=f'campus-flow-workshop-{uuid.uuid4().hex[:6]}',
                    organizer_id=org.id,
                    event_type='Workshop',
                    department='CSE',
                    faculty_coordinator='Dr. Coordinator',
                    venue='Seminar Hall',
                    start_time=Event.start_time.default if hasattr(Event.start_time, 'default') else db.func.now(),
                    end_time=Event.end_time.default if hasattr(Event.end_time, 'default') else db.func.now(),
                    registration_deadline=db.func.now(),
                    description='Official workshop',
                    status=EventStatus.APPROVED
                )
                from datetime import datetime, timedelta
                event.start_time = datetime.utcnow() + timedelta(days=10)
                event.end_time = datetime.utcnow() + timedelta(days=11)
                event.registration_deadline = datetime.utcnow() + timedelta(days=5)
                db.session.add(event)
                db.session.commit()

            reg_res = client.post(f'/student/register/{event.id}', data={}, follow_redirects=True)
            self.assertEqual(reg_res.status_code, 200)

    def test_05_delete_expired_events(self):
        """Verify events are ONLY deleted if expired AND all certificate submissions to students are over."""
        from datetime import datetime, timedelta
        from services.event_service import delete_expired_events, are_certificates_completed
        with self.app.app_context():
            org = User.query.filter_by(role=UserRole.ORGANIZER).first()
            if not org:
                org = User(name="Test Org", email=f"testorg_{uuid.uuid4().hex[:4]}@college.edu", role=UserRole.ORGANIZER, is_active=True)
                org.set_password("pass123")
                db.session.add(org)
                db.session.commit()
            student = User.query.filter_by(role=UserRole.STUDENT).first()
            if not student:
                student = User(name="Test Stu", email=f"teststu_{uuid.uuid4().hex[:4]}@college.edu", role=UserRole.STUDENT, is_active=True)
                student.set_password("pass123")
                db.session.add(student)
                db.session.commit()
            
            # Create an expired event with an attended student but NO certificate issued yet
            event_pending_cert = Event(
                title='Test Expired Event With Pending Cert',
                slug=f'test-pending-cert-{uuid.uuid4().hex[:6]}',
                organizer_id=org.id,
                event_type='Workshop',
                department='CSE',
                faculty_coordinator='Dr. Test',
                description='Event with pending certificate',
                venue='Auditorium',
                start_time=datetime.utcnow() - timedelta(days=5),
                end_time=datetime.utcnow() - timedelta(days=4),
                registration_deadline=datetime.utcnow() - timedelta(days=6),
                status=EventStatus.APPROVED
            )
            db.session.add(event_pending_cert)
            db.session.commit()

            reg = EventRegistration(
                event_id=event_pending_cert.id,
                student_id=student.id,
                registration_code=EventRegistration.generate_registration_code(event_pending_cert.id, student.id),
                status=RegistrationStatus.CONFIRMED
            )
            db.session.add(reg)
            db.session.commit()

            att = AttendanceRecord(
                registration_id=reg.id,
                event_id=event_pending_cert.id,
                student_id=student.id
            )
            db.session.add(att)
            db.session.commit()

            self.assertFalse(are_certificates_completed(event_pending_cert))

            count, deleted, skipped = delete_expired_events(require_certificates_done=True)
            check_event = db.session.get(Event, event_pending_cert.id)
            self.assertIsNotNone(check_event)
            self.assertTrue(any(str(event_pending_cert.id) in s for s in skipped))

            # Assign certificate for the student
            cert_code = Certificate.generate_certificate_code(event_pending_cert.id, student.id)
            cert = Certificate(
                registration_id=reg.id,
                event_id=event_pending_cert.id,
                student_id=student.id,
                certificate_code=cert_code,
                file_path="uploads/certificates/test_cert.pdf",
                original_filename="test_cert.pdf",
                file_type="pdf",
                status=CertificateStatus.MATCHED
            )
            db.session.add(cert)
            db.session.commit()

            self.assertTrue(are_certificates_completed(event_pending_cert))

            count, deleted, skipped = delete_expired_events(require_certificates_done=True)
            self.assertGreaterEqual(count, 1)
            self.assertIsNone(db.session.get(Event, event_pending_cert.id))


if __name__ == '__main__':
    unittest.main()
