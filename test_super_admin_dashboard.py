import unittest
from app import create_app
from models import (
    db, User, UserRole, StudentProfile, FacultyProfile, OrganizerProfile,
    Event, EventRegistration, AttendanceRecord, Certificate, Announcement,
    CollegeDepartment, AuditLog
)

class SuperAdminDashboardTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def login(self, email, password):
        return self.client.post('/auth/login', data={
            'email': email,
            'password': password
        }, follow_redirects=True)

    def logout(self):
        return self.client.get('/auth/logout', follow_redirects=True)

    def test_01_unauthenticated_access_blocked(self):
        """Unauthenticated requests to /admin routes should redirect to login."""
        response = self.client.get('/admin/dashboard', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.headers['Location'])

    def test_02_unauthorized_roles_blocked(self):
        """Students and Organizers should receive 403 Forbidden or redirect when trying to access /admin."""
        # Login as student
        res = self.login('student1@college.edu', 'Pass@123')
        self.assertEqual(res.status_code, 200)

        # Attempt to access /admin/dashboard
        admin_res = self.client.get('/admin/dashboard', follow_redirects=False)
        self.assertEqual(admin_res.status_code, 403)

        # Attempt to access /admin/users
        users_res = self.client.get('/admin/users', follow_redirects=False)
        self.assertEqual(users_res.status_code, 403)
        self.logout()

    def test_03_super_admin_can_access_all_dashboard_views(self):
        """Super Admin can access all 16 modules/views without errors."""
        res = self.login('superadmin@college.edu', 'Admin@123')
        self.assertEqual(res.status_code, 200)

        routes = [
            '/admin/',
            '/admin/dashboard',
            '/admin/users',
            '/admin/users/add',
            '/admin/users/import',
            '/admin/departments',
            '/admin/departments/add',
            '/admin/events',
            '/admin/registrations',
            '/admin/payments',
            '/admin/attendance',
            '/admin/certificates',
            '/admin/announcements',
            '/admin/announcements/create',
            '/admin/audit-logs',
            '/admin/settings',
            '/admin/search?q=test'
        ]

        for r in routes:
            resp = self.client.get(r)
            self.assertEqual(resp.status_code, 200, f"Failed accessing {r}: {resp.status_code}")

        self.logout()

    def test_04_user_crud_and_safety_checks(self):
        """Test adding, editing, toggling, and deleting users via Super Admin."""
        self.login('superadmin@college.edu', 'Admin@123')

        # Add a new test student
        test_email = 'autotest_student@college.edu'
        # Clean up if existed
        existing = User.query.filter_by(email=test_email).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()

        add_res = self.client.post('/admin/users/add', data={
            'name': 'Auto Test Student',
            'email': test_email,
            'phone': '+91 9988776655',
            'password': 'TestPass@123',
            'role': 'STUDENT',
            'roll_number': 'TEST-ROLL-999',
            'department': 'CSE',
            'year_of_study': '3'
        }, follow_redirects=True)
        self.assertEqual(add_res.status_code, 200)

        created_user = User.query.filter_by(email=test_email).first()
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user.role, UserRole.STUDENT)
        self.assertIsNotNone(created_user.student_profile)
        self.assertEqual(created_user.student_profile.roll_number, 'TEST-ROLL-999')

        # Edit user
        edit_res = self.client.post(f'/admin/users/{created_user.id}/edit', data={
            'name': 'Auto Test Student Updated',
            'email': test_email,
            'phone': '+91 9988776600',
            'role': 'STUDENT',
            'department': 'CSE',
            'year_of_study': '4',
            'is_active': 'on'
        }, follow_redirects=True)
        self.assertEqual(edit_res.status_code, 200)

        db.session.refresh(created_user)
        self.assertEqual(created_user.name, 'Auto Test Student Updated')

        # Password Reset
        pwd_res = self.client.post(f'/admin/users/{created_user.id}/reset-password', data={
            'new_password': 'NewPassword@456'
        }, follow_redirects=True)
        self.assertEqual(pwd_res.status_code, 200)
        self.assertTrue(created_user.check_password('NewPassword@456'))

        # Delete user (should hard-delete because student has no event/registration history)
        user_id = created_user.id
        del_res = self.client.post(f'/admin/users/{user_id}/delete', follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)
        self.assertIsNone(User.query.get(user_id))

        self.logout()

    def test_05_soft_deactivation_for_user_with_history(self):
        """Users with history (e.g. student1 with registrations) should be soft-deactivated, not deleted."""
        self.login('superadmin@college.edu', 'Admin@123')

        student1 = User.query.filter_by(email='student1@college.edu').first()
        self.assertIsNotNone(student1)

        # Attempt to delete student1
        del_res = self.client.post(f'/admin/users/{student1.id}/delete', follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)

        # Student should still exist, but is_active is now False
        refreshed = User.query.filter_by(email='student1@college.edu').first()
        self.assertIsNotNone(refreshed)
        self.assertFalse(refreshed.is_active)

        # Re-activate student1 for ongoing tests
        refreshed.is_active = True
        db.session.commit()

        self.logout()

    def test_06_department_management(self):
        """Test department listing and creation."""
        self.login('superadmin@college.edu', 'Admin@123')

        test_code = 'TESTD'
        existing_dept = CollegeDepartment.query.filter_by(code=test_code).first()
        if existing_dept:
            db.session.delete(existing_dept)
            db.session.commit()

        resp = self.client.post('/admin/departments/add', data={
            'code': test_code,
            'name': 'Test Engineering Dept',
            'description': 'Department created for automated tests'
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        created_dept = CollegeDepartment.query.filter_by(code=test_code).first()
        self.assertIsNotNone(created_dept)
        self.assertEqual(created_dept.name, 'Test Engineering Dept')

        # Clean up
        db.session.delete(created_dept)
        db.session.commit()
        self.logout()

    def test_07_attendance_correction_and_audit_log(self):
        """Test manual attendance correction records audit log and updates status."""
        self.login('superadmin@college.edu', 'Admin@123')

        att = AttendanceRecord.query.first()
        if att:
            old_status = att.status
            target_status = 'PRESENT' if old_status != 'PRESENT' else 'ABSENT'

            resp = self.client.post(f'/admin/attendance/{att.id}/correct', data={
                'status': target_status,
                'remarks': 'Automated test correction verification'
            }, follow_redirects=True)
            self.assertEqual(resp.status_code, 200)

            db.session.refresh(att)
            self.assertEqual(att.status, target_status)
            self.assertIn('Automated test correction verification', att.remarks)

            # Verify audit log was created
            log = AuditLog.query.filter_by(target_id=att.id, action='ATTENDANCE_CORRECTED').first()
            self.assertIsNotNone(log)

            # Revert back
            att.status = old_status
            db.session.commit()

        self.logout()

    def test_08_announcement_crud(self):
        """Test Super Admin creating, toggling, and deleting broadcast announcement."""
        self.login('superadmin@college.edu', 'Admin@123')

        create_res = self.client.post('/admin/announcements/create', data={
            'title': 'Test Super Admin Notice',
            'message': 'This is a test notification message.',
            'target_audience': 'ALL',
            'is_pinned': 'on'
        }, follow_redirects=True)
        self.assertEqual(create_res.status_code, 200)

        ann = Announcement.query.filter_by(title='Test Super Admin Notice').first()
        self.assertIsNotNone(ann)
        self.assertTrue(ann.is_pinned)
        self.assertTrue(ann.is_active)

        # Toggle publish
        toggle_res = self.client.post(f'/admin/announcements/{ann.id}/toggle-publish', follow_redirects=True)
        self.assertEqual(toggle_res.status_code, 200)
        db.session.refresh(ann)
        self.assertFalse(ann.is_active)

        # Delete announcement
        del_res = self.client.post(f'/admin/announcements/{ann.id}/delete', follow_redirects=True)
        self.assertEqual(del_res.status_code, 200)
        self.assertIsNone(Announcement.query.get(ann.id))

        self.logout()

if __name__ == '__main__':
    unittest.main()
