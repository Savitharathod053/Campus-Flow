from datetime import datetime
from .user import db

class TargetAudience:
    ALL = 'ALL'
    STUDENTS = 'STUDENTS'
    FACULTY = 'FACULTY'
    HODS = 'HODS'
    ORGANIZERS = 'ORGANIZERS'
    DEPARTMENT = 'DEPARTMENT'

    CHOICES = [ALL, STUDENTS, FACULTY, HODS, ORGANIZERS, DEPARTMENT]


class Announcement(db.Model):
    __tablename__ = 'announcements'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=True, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    target_audience = db.Column(db.String(50), default=TargetAudience.ALL, nullable=False, index=True)
    target_department = db.Column(db.String(100), nullable=True)
    is_pinned = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    event = db.relationship('Event', back_populates='announcements')
    author = db.relationship('User', back_populates='announcements')

    def __repr__(self):
        return f'<Announcement {self.title} (Audience: {self.target_audience})>'
