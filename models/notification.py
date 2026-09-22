"""
Campus Flow - In-App Notification Model
Provides in-app notification tracking for students, organizers, HODs, Dean, and Super Admin.
"""
from datetime import datetime
from .user import db

class NotificationType:
    ORGANIZER_REQUEST = 'ORGANIZER_REQUEST'
    ORGANIZER_APPROVAL = 'ORGANIZER_APPROVAL'
    ORGANIZER_REJECTION = 'ORGANIZER_REJECTION'
    EVENT_REQUEST = 'EVENT_REQUEST'
    EVENT_HOD_APPROVED = 'EVENT_HOD_APPROVED'
    EVENT_HOD_REJECTED = 'EVENT_HOD_REJECTED'
    EVENT_DEAN_APPROVED = 'EVENT_DEAN_APPROVED'
    EVENT_DEAN_REJECTED = 'EVENT_DEAN_REJECTED'
    EVENT_CAPACITY_ALERT = 'EVENT_CAPACITY_ALERT'
    SYSTEM = 'SYSTEM'


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default=NotificationType.SYSTEM, nullable=False, index=True)
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = db.relationship('User', backref=db.backref('notifications_received', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Notification {self.id} (User: {self.user_id}, Title: {self.title[:20]}, Read: {self.is_read})>'


class EventNotificationLog(db.Model):
    """
    Tracks notifications sent for events (e.g. empty slot capacity alerts).
    Enforces uniqueness per (event_id, notification_type, recipient_user_id) to prevent duplicate alerts.
    """
    __tablename__ = 'event_notification_logs'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    status = db.Column(db.String(30), default='SENT', nullable=False)
    details = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('event_id', 'notification_type', 'recipient_user_id', name='uq_event_notif_recipient'),
    )

    event = db.relationship('Event', backref=db.backref('notification_logs', cascade='all, delete-orphan', lazy='dynamic'))
    recipient = db.relationship('User', foreign_keys=[recipient_user_id])

    def __repr__(self):
        return f'<EventNotificationLog Event:{self.event_id} Type:{self.notification_type} User:{self.recipient_user_id}>'

