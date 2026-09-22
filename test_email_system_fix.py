"""
Automated Test Suite for Campus Flow Production Email System Fix.
Verifies:
1. Dual-variable resolution (SMTP_* and MAIL_*)
2. App Password whitespace and quote sanitization
3. Startup configuration check behavior
4. Protected /api/email/test endpoint (unauthorized, invalid email, success)
5. Wrapper functions (send_email, send_registration_confirmation, etc.)
"""
import os
import unittest
from unittest.mock import patch, MagicMock

# Force testing configuration
os.environ['TESTING'] = 'True'

from app import create_app
from services.email_service import (
    get_mail_config,
    check_email_startup_config,
    send_email,
    send_registration_confirmation,
    send_hod_notification,
    send_organizer_notification,
    send_otp_email,
    send_password_reset_email,
    send_test_email
)


class TestEmailSystemFix(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()

    def test_01_smtp_variable_precedence_and_mapping(self):
        """Verify standard SMTP_* variables are recognized and properly structured."""
        with patch.dict(os.environ, {
            'SMTP_HOST': 'smtp.gmail.com',
            'SMTP_PORT': '587',
            'SMTP_USERNAME': 'admin@campusflow.edu',
            'SMTP_PASSWORD': 'abcd efgh ijkl mnop',
            'SMTP_FROM_EMAIL': 'notifications@campusflow.edu',
            'SMTP_FROM_NAME': 'Campus Flow Notifications'
        }, clear=False):
            cfg = get_mail_config()
            self.assertEqual(cfg['SMTP_HOST'], 'smtp.gmail.com')
            self.assertEqual(cfg['SMTP_PORT'], 587)
            self.assertEqual(cfg['SMTP_USERNAME'], 'admin@campusflow.edu')
            # Gmail App Password spaces must be stripped
            self.assertEqual(cfg['SMTP_PASSWORD'], 'abcdefghijklmnop')
            self.assertEqual(cfg['SMTP_FROM_EMAIL'], 'notifications@campusflow.edu')
            self.assertEqual(cfg['SMTP_FROM_NAME'], 'Campus Flow Notifications')
            # Legacy keys also populated for backward compatibility
            self.assertEqual(cfg['MAIL_SERVER'], 'smtp.gmail.com')
            self.assertEqual(cfg['MAIL_PORT'], 587)
            self.assertEqual(cfg['MAIL_USERNAME'], 'admin@campusflow.edu')
            self.assertEqual(cfg['MAIL_PASSWORD'], 'abcdefghijklmnop')

    def test_02_mail_legacy_fallback(self):
        """Verify legacy MAIL_* variables work if SMTP_* is not set."""
        env_dict = {
            'MAIL_SERVER': 'smtp.gmail.com',
            'MAIL_PORT': '465',
            'MAIL_USERNAME': 'legacy@campusflow.edu',
            'MAIL_PASSWORD': '"legacy_app_pass"',
            'MAIL_DEFAULT_SENDER': 'Campus Flow <legacy@campusflow.edu>'
        }
        # Remove any existing SMTP_*
        for k in ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM_EMAIL', 'SMTP_FROM_NAME']:
            if k in os.environ:
                del os.environ[k]

        with patch.dict(os.environ, env_dict, clear=False):
            cfg = get_mail_config()
            self.assertEqual(cfg['SMTP_HOST'], 'smtp.gmail.com')
            self.assertEqual(cfg['SMTP_PORT'], 465)
            self.assertEqual(cfg['SMTP_USERNAME'], 'legacy@campusflow.edu')
            # Quotes stripped
            self.assertEqual(cfg['SMTP_PASSWORD'], 'legacy_app_pass')
            self.assertEqual(cfg['MAIL_SERVER'], 'smtp.gmail.com')
            self.assertEqual(cfg['MAIL_PORT'], 465)

    def test_03_startup_config_check_ok(self):
        """Verify check_email_startup_config logs OK when all required variables exist."""
        with patch.dict(os.environ, {
            'SMTP_HOST': 'smtp.gmail.com',
            'SMTP_PORT': '587',
            'SMTP_USERNAME': 'bot@campusflow.edu',
            'SMTP_PASSWORD': 'secretpassword',
            'SMTP_FROM_EMAIL': 'bot@campusflow.edu'
        }, clear=False):
            ok, msg = check_email_startup_config()
            self.assertTrue(ok)
            self.assertIn("Email configuration: OK", msg)
            self.assertNotIn("secretpassword", msg)

    def test_04_startup_config_check_missing(self):
        """Verify check_email_startup_config reports missing variables without crashing or leaking secrets."""
        # Unset SMTP_PASSWORD and MAIL_PASSWORD
        clean_env = {
            'SMTP_HOST': 'smtp.gmail.com',
            'SMTP_PORT': '587',
            'SMTP_USERNAME': 'bot@campusflow.edu',
            'SMTP_PASSWORD': '',
            'MAIL_PASSWORD': '',
            'SMTP_FROM_EMAIL': 'bot@campusflow.edu'
        }
        with patch.dict(os.environ, clean_env, clear=False):
            ok, msg = check_email_startup_config()
            self.assertFalse(ok)
            self.assertIn("Missing", msg)
            self.assertIn("SMTP_PASSWORD", msg)

    def test_05_api_email_test_unauthorized(self):
        """Verify /api/email/test blocks unauthenticated and tokenless requests."""
        resp = self.client.get('/api/email/test')
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error_type'], 'Unauthorized')

    def test_06_api_email_test_invalid_email(self):
        """Verify /api/email/test validates recipient email."""
        secret = self.app.config.get('SECRET_KEY')
        resp = self.client.post(
            '/api/email/test',
            headers={'Authorization': f'Bearer {secret}'},
            json={'recipient_email': 'invalid-email-address'}
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['success'])
        self.assertEqual(data['error_type'], 'ValidationError')

    def test_07_api_email_test_success_with_token(self):
        """Verify /api/email/test succeeds with valid admin token in testing mode."""
        secret = self.app.config.get('SECRET_KEY')
        with patch('services.email_service.send_test_email') as mock_test_send:
            mock_test_send.return_value = (True, "Test email sent successfully", None)

            resp = self.client.post(
                '/api/email/test',
                headers={'Authorization': f'Bearer {secret}'},
                json={'recipient_email': 'testrecipient@example.com'}
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['success'])
            self.assertEqual(data['message'], "Test email sent successfully")
            self.assertNotIn('error_type', data)

    def test_08_send_email_and_wrappers(self):
        """Verify send_email and wrapper functions exist and execute safely."""
        with patch('services.email_service.dispatch_email') as mock_dispatch:
            mock_dispatch.return_value = True

            res = send_email(
                to_email="student@campusflow.edu",
                subject="Notification",
                body_text="Test notification body"
            )
            self.assertTrue(res)
            mock_dispatch.assert_called()

            res_otp = send_otp_email("student@campusflow.edu", "123456")
            self.assertTrue(res_otp)

            res_reset = send_password_reset_email("student@campusflow.edu", "https://campusflow.edu/reset")
            self.assertTrue(res_reset)


if __name__ == '__main__':
    unittest.main()
