"""
Automated Test Suite for Campus Flow Notification System UI and Synchronization Fix.
Verifies:
1. Database read/unread state persistence
2. Unread notification counting
3. POST /notifications/<id>/read endpoint (auth, 404, success, unread_count response)
4. POST /notifications/read/<id> alias endpoint
5. POST /notifications/read-all endpoint
6. GET /notifications/unread-count and GET /notifications endpoints
7. Data isolation between users
8. Idempotent read marking
"""
import os
import unittest
from datetime import datetime

os.environ['TESTING'] = 'True'

from app import create_app
from models import db, User, UserRole, Notification, NotificationType
from services.notification_service import (
    create_notification,
    get_unread_count,
    get_user_notifications,
    mark_as_read,
    mark_all_as_read
)


class TestNotificationSystemFix(unittest.TestCase):

    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()

        # Create unique test users
        self.timestamp = int(datetime.utcnow().timestamp())
        self.user1 = User(
            name=f"Notif User 1 {self.timestamp}",
            email=f"notif.user1.{self.timestamp}@example.com",
            role=UserRole.STUDENT,
            is_active=True
        )
        self.user1.set_password("Password123!")

        self.user2 = User(
            name=f"Notif User 2 {self.timestamp}",
            email=f"notif.user2.{self.timestamp}@example.com",
            role=UserRole.STUDENT,
            is_active=True
        )
        self.user2.set_password("Password123!")

        db.session.add(self.user1)
        db.session.add(self.user2)
        db.session.commit()

    def tearDown(self):
        # Cleanup test notifications and users
        Notification.query.filter(Notification.user_id.in_([self.user1.id, self.user2.id])).delete(synchronize_session=False)
        db.session.delete(self.user1)
        db.session.delete(self.user2)
        db.session.commit()
        self.app_context.pop()

    def test_01_create_notification_and_unread_count(self):
        """Verify notification creation has is_read=False and increments unread count."""
        n1 = create_notification(self.user1.id, "Title 1", "Message 1", NotificationType.SYSTEM)
        n2 = create_notification(self.user1.id, "Title 2", "Message 2", NotificationType.EVENT_CAPACITY_ALERT)
        
        self.assertIsNotNone(n1)
        self.assertFalse(n1.is_read)
        self.assertEqual(get_unread_count(self.user1.id), 2)
        self.assertEqual(get_unread_count(self.user2.id), 0)

    def test_02_mark_single_as_read_persists_in_database(self):
        """Verify mark_as_read updates is_read in database and decrements unread count."""
        n1 = create_notification(self.user1.id, "Title 1", "Message 1")
        n2 = create_notification(self.user1.id, "Title 2", "Message 2")

        res = mark_as_read(n1.id, user_id=self.user1.id)
        self.assertIsNotNone(res)
        self.assertTrue(res.is_read)

        # Refresh from DB
        db.session.expire_all()
        refreshed = db.session.get(Notification, n1.id)
        self.assertTrue(refreshed.is_read)
        self.assertEqual(get_unread_count(self.user1.id), 1)

    def test_03_api_unauthorized_rejection(self):
        """Verify /notifications/<id>/read returns 401 when not logged in."""
        n = create_notification(self.user1.id, "Secret", "Message")
        resp = self.client.post(f"/notifications/{n.id}/read")
        self.assertEqual(resp.status_code, 401)
        data = resp.get_json()
        self.assertFalse(data['success'])

    def test_04_api_mark_as_read_success_and_unread_count_response(self):
        """Verify POST /notifications/<id>/read marks read and returns remaining count."""
        n1 = create_notification(self.user1.id, "Alert 1", "Body 1")
        n2 = create_notification(self.user1.id, "Alert 2", "Body 2")
        n3 = create_notification(self.user1.id, "Alert 3", "Body 3")

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user1.id

        resp = self.client.post(f"/notifications/{n1.id}/read")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_read'])
        self.assertEqual(data['notification_id'], n1.id)
        self.assertEqual(data['unread_count'], 2)

        # Verify DB directly
        refreshed = db.session.get(Notification, n1.id)
        self.assertTrue(refreshed.is_read)

    def test_05_api_isolation_cannot_mark_other_users_notification(self):
        """Verify User 2 cannot mark User 1's notification as read."""
        n = create_notification(self.user1.id, "User 1 Only", "Body")

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user2.id

        resp = self.client.post(f"/notifications/{n.id}/read")
        self.assertEqual(resp.status_code, 404)
        
        # User 1's notification should still be unread
        db.session.expire_all()
        refreshed = db.session.get(Notification, n.id)
        self.assertFalse(refreshed.is_read)

    def test_06_api_alias_endpoint(self):
        """Verify alias /notifications/read/<id> also works correctly."""
        n = create_notification(self.user1.id, "Alias Test", "Body")

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user1.id

        resp = self.client.post(f"/notifications/read/{n.id}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['unread_count'], 0)

    def test_07_api_mark_all_as_read(self):
        """Verify POST /notifications/read-all marks all notifications as read."""
        create_notification(self.user1.id, "N1", "M1")
        create_notification(self.user1.id, "N2", "M2")
        create_notification(self.user1.id, "N3", "M3")

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user1.id

        self.assertEqual(get_unread_count(self.user1.id), 3)

        resp = self.client.post("/notifications/read-all")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['unread_count'], 0)

        # Database confirmation
        self.assertEqual(get_unread_count(self.user1.id), 0)

    def test_08_api_get_unread_count_and_notifications_list(self):
        """Verify GET /notifications/unread-count and GET /notifications return correct payloads."""
        create_notification(self.user1.id, "List Test 1", "Body 1")
        create_notification(self.user1.id, "List Test 2", "Body 2")

        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user1.id

        # Check count endpoint
        resp_count = self.client.get("/notifications/unread-count")
        self.assertEqual(resp_count.status_code, 200)
        self.assertEqual(resp_count.get_json()['unread_count'], 2)

        # Check list endpoint
        resp_list = self.client.get("/notifications")
        self.assertEqual(resp_list.status_code, 200)
        list_data = resp_list.get_json()
        self.assertTrue(list_data['success'])
        self.assertEqual(list_data['unread_count'], 2)
        self.assertEqual(len(list_data['notifications']), 2)
        self.assertIn('title', list_data['notifications'][0])
        self.assertIn('is_read', list_data['notifications'][0])

    def test_09_idempotent_mark_read(self):
        """Verify marking an already read notification again does not corrupt state."""
        n = create_notification(self.user1.id, "Double Mark", "Body")
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.user1.id

        # First mark
        resp1 = self.client.post(f"/notifications/{n.id}/read")
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.get_json()['unread_count'], 0)

        # Second mark (idempotent)
        resp2 = self.client.post(f"/notifications/{n.id}/read")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.get_json()['unread_count'], 0)
        self.assertTrue(resp2.get_json()['is_read'])


if __name__ == '__main__':
    unittest.main()
