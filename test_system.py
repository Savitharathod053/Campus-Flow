import os
import unittest
import json
import uuid
from app import create_app
from config import Config
from models import db, User, Event, OrganizerProfile, EventRegistration, RegistrationStatus, AttendanceRecord, Certificate, CertificateStatus, PaymentStatus, EventStatus

class FastFestTestConfig(Config):
    TESTING = True
    # If DATABASE_URL is set to a live database, use it; fallback to fastfest.db for offline unit tests
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or os.environ.get('DATABASE_URL') or 'sqlite:///fastfest.db'

class FastFestSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure database is accessible for test run
        db_url = FastFestTestConfig.SQLALCHEMY_DATABASE_URI
        if db_url.startswith('mssql') or db_url.startswith('sqlserver'):
            try:
                import pyodbc
                conn_str = (
                    "Driver={ODBC Driver 18 for SQL Server};"
                    "Server=localhost;"
                    "Database=fastfest;"
                    "Trusted_Connection=yes;"
                    "TrustServerCertificate=yes;"
                )
                conn = pyodbc.connect(conn_str)
                conn.close()
            except Exception:
                FastFestTestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///fastfest.db'
        elif db_url.startswith('mysql://') or db_url.startswith('mysql+pymysql://'):
            try:
                from migrate_sqlite_to_mysql import parse_mysql_conn_params
                import pymysql
                params = parse_mysql_conn_params(db_url)
                conn = pymysql.connect(**params)
                conn.close()
            except Exception:
                # Use local fastfest.db fallback for offline test execution
                FastFestTestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///fastfest.db'
        elif db_url.startswith('postgresql://') or db_url.startswith('postgres://'):
            try:
                import psycopg2
                conn = psycopg2.connect(db_url)
                conn.close()
            except Exception:
                FastFestTestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///fastfest.db'

    def setUp(self):
        self.app = create_app(FastFestTestConfig)
        self.app.config['TESTING'] = True

    def test_01_public_pages(self):
        """Verify home, event list, and event detail pages load properly."""
        client = self.app.test_client()
        with self.app.app_context():
            res = client.get('/')
            self.assertEqual(res.status_code, 200)
            self.assertIn(b'FastFest', res.data)

            res = client.get('/events')
            self.assertEqual(res.status_code, 200)

            event = Event.query.first()
            if event:
                res = client.get(f'/events/{event.slug}')
                self.assertEqual(res.status_code, 200)
                self.assertIn(event.title.encode('utf-8'), res.data)

    def test_02_organizer_registration_and_department_admin_approval(self):
        """Verify new organizer starts unapproved and requires department admin approval."""
        unique_id = uuid.uuid4().hex[:6]
        test_email = f"test.mech.{unique_id}@college.edu"

        with self.app.app_context():
            client = self.app.test_client()

            # 1. Register new organizer in MECH department
            reg_res = client.post('/auth/register/organizer', data={
                'name': 'Test MECH Organizer',
                'email': test_email,
                'organization_name': f'Automotive Society {unique_id}',
                'department': 'MECH',
                'designation': 'President',
                'phone': '+91 9988776655',
                'password': 'Pass@123',
                'confirm_password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(reg_res.status_code, 200)
            self.assertIn(b'department faculty admin', reg_res.data)

            # 2. Try to log in before approval -> Should be prevented with department admin name
            login_fail = client.post('/auth/login', data={
                'email': test_email,
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(login_fail.status_code, 200)
            self.assertIn(b'pending approval by your department faculty admin', login_fail.data)
            self.assertIn(b'Dr. R. Ramesh', login_fail.data)

            # 3. Log in as MECH Faculty Admin and approve
            admin_client = self.app.test_client()
            admin_client.post('/auth/login', data={
                'email': 'admin.mech@college.edu',
                'password': 'Pass@123'
            }, follow_redirects=True)

            org_user = User.query.filter_by(email=test_email).first()
            self.assertIsNotNone(org_user)
            org_prof = org_user.organizer_profile
            self.assertIsNotNone(org_prof)

            approve_res = admin_client.post(f'/admin/organizers/{org_prof.id}/action', data={
                'action': 'approve'
            }, follow_redirects=True)
            self.assertEqual(approve_res.status_code, 200)

            # 4. Now the organizer logs in successfully with new client
            org_client = self.app.test_client()
            login_success = org_client.post('/auth/login', data={
                'email': test_email,
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(login_success.status_code, 200)
            self.assertIn(b'Organizer Dashboard', login_success.data)

    def test_03_student_auth_and_registration(self):
        """Verify student login and event registration flow."""
        client = self.app.test_client()
        with self.app.app_context():
            login_res = client.post('/auth/login', data={
                'email': 'student4@college.edu',
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(login_res.status_code, 200)

            event = Event.query.filter_by(status=EventStatus.APPROVED).first()
            if not event:
                event = Event.query.first()
            self.assertIsNotNone(event)

            reg_res = client.post(f'/student/register/{event.id}', data={
                'custom_field_1': 'Testing Team',
                'custom_field_2': 'https://github.com/student4',
                'custom_field_3': 'M'
            }, follow_redirects=True)
            self.assertEqual(reg_res.status_code, 200)

    def test_04_organizer_attendance_and_duplicate_check(self):
        """Verify QR scanner API marks attendance and catches duplicates."""
        client = self.app.test_client()
        with self.app.app_context():
            client.post('/auth/login', data={
                'email': 'organizer@college.edu',
                'password': 'Pass@123'
            }, follow_redirects=True)

            reg = EventRegistration.query.first()
            self.assertIsNotNone(reg)

            # First scan
            res1 = client.post('/organizer/attendance/mark', 
                data=json.dumps({
                    'registration_code': reg.registration_code,
                    'event_id': reg.event_id
                }),
                content_type='application/json'
            )
            self.assertIn(res1.status_code, [200, 400])

            # Second scan -> Duplicate alert
            res2 = client.post('/organizer/attendance/mark', 
                data=json.dumps({
                    'registration_code': reg.registration_code,
                    'event_id': reg.event_id
                }),
                content_type='application/json'
            )
            self.assertEqual(res2.status_code, 200)
            data = json.loads(res2.data)
            self.assertEqual(data.get('status'), 'duplicate')

    def test_05_admin_approvals_and_reports(self):
        """Verify admin can view pending approvals and reports."""
        client = self.app.test_client()
        with self.app.app_context():
            login_res = client.post('/auth/login', data={
                'email': 'admin@college.edu',
                'password': 'Pass@123'
            }, follow_redirects=True)
            self.assertEqual(login_res.status_code, 200)

            res_approvals = client.get('/admin/pending-approvals')
            self.assertEqual(res_approvals.status_code, 200)

            res_reports = client.get('/admin/reports')
            self.assertEqual(res_reports.status_code, 200)
            self.assertIn(b'Participation Analytics', res_reports.data)

    def test_06_delete_expired_events(self):
        """Verify events are ONLY deleted if expired AND all certificate submissions to students are over."""
        from datetime import datetime, timedelta
        from services.event_service import delete_expired_events, are_certificates_completed
        with self.app.app_context():
            org = User.query.filter_by(role='ORGANIZER').first() or User.query.first()
            student = User.query.filter_by(role='STUDENT').first() or User.query.first()
            
            # 1. Create an expired event with an attended student but NO certificate issued yet
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

            # Add confirmed registration and attendance record
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

            # Certificate is NOT issued yet -> are_certificates_completed must be False
            self.assertFalse(are_certificates_completed(event_pending_cert))

            # Running cleanup MUST NOT delete this event
            count, deleted, skipped = delete_expired_events(require_certificates_done=True)
            check_event = db.session.get(Event, event_pending_cert.id)
            self.assertIsNotNone(check_event)
            self.assertTrue(any(str(event_pending_cert.id) in s for s in skipped))

            # 2. Now upload/assign certificate for the student
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

            # All certificates are now completed
            self.assertTrue(are_certificates_completed(event_pending_cert))

            # Running cleanup now MUST delete the event
            count, deleted, skipped = delete_expired_events(require_certificates_done=True)
            self.assertGreaterEqual(count, 1)
            self.assertIsNone(db.session.get(Event, event_pending_cert.id))

if __name__ == '__main__':
    unittest.main()
