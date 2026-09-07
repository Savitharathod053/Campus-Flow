import unittest
from app import create_app
from config import Config
from models import db, User, UserRole, OrganizerProfile

class TestSQLServerAuthFlow(unittest.TestCase):
    def setUp(self):
        self.app = create_app(Config)
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_01_stale_session_user_281(self):
        """
        Verify that a session containing user_id = 281 (which does not exist in DB)
        gracefully redirects to /auth/login, cleans up the stale session, and does NOT
        throw a 500 error or Invalid object name 'users' exception.
        """
        with self.client.session_transaction() as sess:
            sess['user_id'] = 281
            sess['role'] = 'organizer'

        # Attempt to access /organizer/events/create
        response = self.client.get('/organizer/events/create', follow_redirects=False)

        # Must redirect to login, NOT 500
        self.assertEqual(response.status_code, 302)
        self.assertIn('/auth/login', response.headers.get('Location', ''))

        # Follow redirect and verify clean response and flash message
        follow_response = self.client.get('/organizer/events/create', follow_redirects=True)
        self.assertEqual(follow_response.status_code, 200)
        self.assertIn(b'Your account is inactive or not found', follow_response.data)

        # Verify session is cleaned up
        with self.client.session_transaction() as sess:
            self.assertNotIn('user_id', sess)

    def test_02_organizer_access_events_create(self):
        """
        Verify that a valid organizer can access /organizer/events/create with 200 OK
        and view the event creation form.
        """
        with self.app.app_context():
            # Clean up any previous test user
            existing = User.query.filter_by(email='test_org_verifier@campusflow.edu').first()
            if existing:
                db.session.delete(existing)
                db.session.commit()

            # Create an organizer user
            test_org = User(
                name='Test Organizer Verifier',
                email='test_org_verifier@campusflow.edu',
                role=UserRole.ORGANIZER,
                is_active=True
            )
            test_org.set_password('OrganizerPass123!')
            db.session.add(test_org)
            db.session.commit()

            org_profile = OrganizerProfile(
                user_id=test_org.id,
                organization_name='Campus Tech Club',
                department='CSE'
            )
            db.session.add(org_profile)
            db.session.commit()

            test_user_id = test_org.id

        try:
            # Login as organizer
            with self.client.session_transaction() as sess:
                sess['user_id'] = test_user_id
                sess['role'] = 'organizer'

            # Access /organizer/events/create
            response = self.client.get('/organizer/events/create')
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'Create Campus Event', response.data)
            self.assertIn(b'Event Title *', response.data)
            self.assertIn(b'Organizing Department *', response.data)
            self.assertIn(b'Submit Event for Approval', response.data)

        finally:
            # Clean up
            with self.app.app_context():
                user_to_del = db.session.get(User, test_user_id)
                if user_to_del:
                    db.session.delete(user_to_del)
                    db.session.commit()

    def test_03_error_handler_resilience(self):
        """
        Verify that if an unhandled error or DB error occurs during request processing,
        the 500 error handler rolls back and renders without crashing in inject_global_vars.
        """
        app_err = create_app(Config)
        app_err.config['TESTING'] = True
        app_err.config['PROPAGATE_EXCEPTIONS'] = False

        @app_err.route('/test-simulate-500-error')
        def simulate_failure():
            raise RuntimeError("Simulated internal runtime error")

        client = app_err.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 999999

        response = client.get('/test-simulate-500-error')
        self.assertEqual(response.status_code, 500)
        self.assertTrue(b'500' in response.data or b'Something Went Wrong' in response.data)


if __name__ == '__main__':
    unittest.main()
