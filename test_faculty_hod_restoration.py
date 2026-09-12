"""
Campus Flow - Verification Test Suite for Role Redirection and Isolation
Validates login redirection, portal routes, and strict role isolation for:
- Student
- Organizer
- HOD
- Students Affairs Dean
- Super Admin
"""

import unittest
from app import create_app
from models import db, User, UserRole

class RoleIsolationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def login(self, identifier, password):
        return self.client.post('/auth/login', data={
            'identifier': identifier,
            'password': password
        }, follow_redirects=False)

    def logout(self):
        return self.client.get('/auth/logout', follow_redirects=True)

    # -------------------------------------------------------------------------
    # 1. HOD TESTS
    # -------------------------------------------------------------------------
    def test_01_hod_login_and_dashboard(self):
        """HOD login redirects to /hod/dashboard and views are accessible."""
        resp = self.login('admin.cse@college.edu', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/hod/dashboard', resp.headers['Location'])

        dash = self.client.get('/hod/dashboard')
        self.assertEqual(dash.status_code, 200)
        self.assertIn(b'HOD', dash.data)

        # HOD cannot access Dean or Super Admin
        self.assertEqual(self.client.get('/dean/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 2. STUDENTS AFFAIRS DEAN TESTS
    # -------------------------------------------------------------------------
    def test_02_dean_login_and_dashboard(self):
        """Dean login redirects to /dean/dashboard and views are accessible."""
        resp = self.login('admin@college.edu', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/dean/dashboard', resp.headers['Location'])

        dash = self.client.get('/dean/dashboard')
        self.assertEqual(dash.status_code, 200)

        # Dean cannot access Super Admin
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 3. SUPER ADMIN TESTS
    # -------------------------------------------------------------------------
    def test_03_super_admin_login_and_dashboard(self):
        """Super Admin login redirects to /admin/dashboard and views are accessible."""
        resp = self.login('superadmin@college.edu', 'Admin@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/dashboard', resp.headers['Location'])

        dash = self.client.get('/admin/dashboard')
        self.assertEqual(dash.status_code, 200)

        for path in ['/admin/events', '/admin/users', '/admin/departments', '/admin/registrations', '/admin/announcements', '/admin/audit-logs', '/admin/settings']:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"Failed accessing {path}")
        self.logout()

    # -------------------------------------------------------------------------
    # 4. STUDENT TESTS
    # -------------------------------------------------------------------------
    def test_04_student_login_and_isolation(self):
        """Student login with Roll Number redirects to /student/dashboard."""
        resp = self.login('21CS001', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/student/dashboard', resp.headers['Location'])

        dash = self.client.get('/student/dashboard')
        self.assertEqual(dash.status_code, 200)

        # Blocked from administrative and departmental portals
        self.assertEqual(self.client.get('/hod/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/dean/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/organizer/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 5. ORGANIZER TESTS
    # -------------------------------------------------------------------------
    def test_05_organizer_login_and_isolation(self):
        """Organizer login with Roll Number redirects to /organizer/dashboard."""
        resp = self.login('DEMO2026ORG001', 'Demo@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/organizer/dashboard', resp.headers['Location'])

        dash = self.client.get('/organizer/dashboard')
        self.assertEqual(dash.status_code, 200)

        # Blocked from other portals
        self.assertEqual(self.client.get('/hod/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/dean/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/student/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 6. UNAUTHENTICATED TESTS
    # -------------------------------------------------------------------------
    def test_06_unauthenticated_redirection(self):
        """Unauthenticated requests to any portal route redirect to login."""
        for path in ['/hod/dashboard', '/dean/dashboard', '/admin/dashboard', '/student/dashboard', '/organizer/dashboard']:
            resp = self.client.get(path, follow_redirects=False)
            self.assertEqual(resp.status_code, 302, f"Expected redirect on {path}")
            self.assertIn('/auth/login', resp.headers['Location'])

if __name__ == '__main__':
    unittest.main()

