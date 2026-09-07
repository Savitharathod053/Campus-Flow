"""
Campus Flow - Verification Test Suite for Faculty and HOD Restoration
Validates login redirection, portal routes, and strict role isolation for:
- Student
- Faculty
- HOD
- Organizer
- Admin
"""

import unittest
from app import create_app
from models import db, User, UserRole

class FacultyHODRestorationTestCase(unittest.TestCase):
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
        }, follow_redirects=False)

    def logout(self):
        return self.client.get('/auth/logout', follow_redirects=True)

    # -------------------------------------------------------------------------
    # 1. FACULTY TESTS
    # -------------------------------------------------------------------------
    def test_01_faculty_login_and_dashboard(self):
        """Faculty login redirects to /faculty/dashboard and views are accessible."""
        resp = self.login('faculty.demo@college.edu', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/faculty/dashboard', resp.headers['Location'])

        # Access dashboard
        dash = self.client.get('/faculty/dashboard')
        self.assertEqual(dash.status_code, 200)
        self.assertIn(b'Faculty Portal', dash.data)

        # Access other faculty routes
        for path in ['/faculty/events', '/faculty/students', '/faculty/attendance', '/faculty/announcements']:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"Failed accessing {path}")

        # Faculty cannot access HOD or Admin
        self.assertEqual(self.client.get('/hod/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 2. HOD TESTS
    # -------------------------------------------------------------------------
    def test_02_hod_login_and_dashboard(self):
        """HOD login redirects to /hod/dashboard and views are accessible."""
        resp = self.login('jabbar@gmail.com', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/hod/dashboard', resp.headers['Location'])

        # Access dashboard
        dash = self.client.get('/hod/dashboard')
        self.assertEqual(dash.status_code, 200)
        self.assertIn(b'HOD Portal', dash.data)

        # Access other HOD routes
        for path in ['/hod/events', '/hod/faculty', '/hod/students', '/hod/announcements']:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"Failed accessing {path}")

        # HOD cannot access Faculty or Admin
        self.assertEqual(self.client.get('/faculty/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 3. ADMIN TESTS
    # -------------------------------------------------------------------------
    def test_03_admin_login_and_dashboard(self):
        """Admin login redirects to /admin/dashboard and views are accessible."""
        resp = self.login('admin@college.edu', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/admin/dashboard', resp.headers['Location'])

        # Access dashboard
        dash = self.client.get('/admin/dashboard')
        self.assertEqual(dash.status_code, 200)

        # Access other admin routes
        for path in ['/admin/events', '/admin/users', '/admin/departments', '/admin/registrations', '/admin/announcements', '/admin/audit-logs', '/admin/settings']:
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, f"Failed accessing {path}")

        # Admin cannot access Faculty or HOD
        self.assertEqual(self.client.get('/faculty/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/hod/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 4. STUDENT TESTS
    # -------------------------------------------------------------------------
    def test_04_student_login_and_isolation(self):
        """Student login redirects to /student/dashboard and cannot access other portals."""
        resp = self.login('student1@college.edu', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/student/dashboard', resp.headers['Location'])

        # Access student dashboard
        dash = self.client.get('/student/dashboard')
        self.assertEqual(dash.status_code, 200)

        # Blocked from administrative and departmental portals
        self.assertEqual(self.client.get('/faculty/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/hod/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/organizer/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 5. ORGANIZER TESTS
    # -------------------------------------------------------------------------
    def test_05_organizer_login_and_isolation(self):
        """Organizer login redirects to /organizer/dashboard and cannot access other portals."""
        resp = self.login('organizer@college.edu', 'Pass@123')
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/organizer/dashboard', resp.headers['Location'])

        # Access organizer dashboard
        dash = self.client.get('/organizer/dashboard')
        self.assertEqual(dash.status_code, 200)

        # Blocked from other portals
        self.assertEqual(self.client.get('/faculty/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/hod/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/admin/dashboard').status_code, 403)
        self.assertEqual(self.client.get('/student/dashboard').status_code, 403)
        self.logout()

    # -------------------------------------------------------------------------
    # 6. UNAUTHENTICATED TESTS
    # -------------------------------------------------------------------------
    def test_06_unauthenticated_redirection(self):
        """Unauthenticated requests to any portal route redirect to login."""
        for path in ['/faculty/dashboard', '/hod/dashboard', '/admin/dashboard', '/student/dashboard', '/organizer/dashboard']:
            resp = self.client.get(path, follow_redirects=False)
            self.assertEqual(resp.status_code, 302, f"Expected redirect on {path}")
            self.assertIn('/auth/login', resp.headers['Location'])

if __name__ == '__main__':
    unittest.main()
