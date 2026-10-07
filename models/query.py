from datetime import datetime
from .user import db


class QueryStatus:
    PENDING = 'Pending'
    REPLIED = 'Replied'
    CLOSED = 'Closed'

    CHOICES = [PENDING, REPLIED, CLOSED]


class EventQuery(db.Model):
    """
    Direct student-to-organizer query linked to a specific event.
    """
    __tablename__ = 'event_queries'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Auto-filled student snapshot & event info
    student_name = db.Column(db.String(100), nullable=False)
    student_roll_number = db.Column(db.String(50), nullable=True)
    student_email = db.Column(db.String(150), nullable=False)
    event_name = db.Column(db.String(200), nullable=False)

    # Query content
    subject = db.Column(db.String(200), nullable=True)
    query_text = db.Column(db.Text, nullable=False)

    # Organizer reply
    reply_text = db.Column(db.Text, nullable=True)

    # Status: 'Pending', 'Replied', 'Closed'
    status = db.Column(db.String(20), default=QueryStatus.PENDING, nullable=False, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    replied_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    event = db.relationship('Event', back_populates='queries')
    student = db.relationship('User', foreign_keys=[student_id], back_populates='student_queries')
    organizer = db.relationship('User', foreign_keys=[organizer_id], back_populates='organizer_queries')

    @property
    def is_pending(self):
        return self.status == QueryStatus.PENDING

    @property
    def is_replied(self):
        return self.status == QueryStatus.REPLIED

    @property
    def is_closed(self):
        return self.status == QueryStatus.CLOSED

    def __repr__(self):
        return f'<EventQuery #{self.id} {self.student_name} -> {self.event_name} ({self.status})>'
