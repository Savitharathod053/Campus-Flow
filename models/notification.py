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
