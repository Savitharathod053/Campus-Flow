"""
Campus Flow - In-App Notification Service
Helpers to dispatch, query, and mark in-app notifications for users.
"""
import logging
from datetime import datetime
from models import db, Notification, NotificationType

logger = logging.getLogger(__name__)


def create_notification(user_id, title, message, notification_type=NotificationType.SYSTEM, link=None):
    """
    Creates an in-app notification for a given user.
    """
    try:
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=notification_type,
            link=link,
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.session.add(notification)
        db.session.commit()
        logger.info(f"[NOTIFICATION CREATED] User {user_id}: {title}")
        return notification
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating in-app notification for user {user_id}: {e}", exc_info=True)
        return None


def get_user_notifications(user_id, limit=20, unread_only=False):
    """
    Retrieves recent notifications for a user.
    """
    try:
        query = Notification.query.filter_by(user_id=user_id)
        if unread_only:
            query = query.filter_by(is_read=False)
        return query.order_by(Notification.created_at.desc()).limit(limit).all()
    except Exception as e:
        logger.error(f"Error fetching notifications for user {user_id}: {e}", exc_info=True)
        return []


def get_unread_count(user_id):
    """
    Returns the count of unread notifications for a user.
    """
    if not user_id:
        return 0
    try:
        return Notification.query.filter_by(user_id=user_id, is_read=False).count()
    except Exception as e:
        logger.error(f"Error counting unread notifications for user {user_id}: {e}", exc_info=True)
        return 0


def mark_as_read(notification_id, user_id=None):
    """
    Marks a specific notification as read.
    """
    try:
        query = Notification.query.filter_by(id=notification_id)
        if user_id:
            query = query.filter_by(user_id=user_id)
        notification = query.first()
        if notification:
            notification.is_read = True
            db.session.commit()
            return True
        return False
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking notification {notification_id} as read: {e}", exc_info=True)
        return False


def mark_all_as_read(user_id):
    """
    Marks all notifications for a user as read.
    """
    try:
        Notification.query.filter_by(user_id=user_id, is_read=False).update({'is_read': True})
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error marking all notifications as read for user {user_id}: {e}", exc_info=True)
        return False
