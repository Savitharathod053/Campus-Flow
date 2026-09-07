from datetime import datetime
from .user import db

class AttendanceSessionStatus:
    UPCOMING = 'UPCOMING'
    ACTIVE = 'ACTIVE'
    COMPLETED = 'COMPLETED'
    CANCELLED = 'CANCELLED'

    CHOICES = [UPCOMING, ACTIVE, COMPLETED, CANCELLED]


class AttendanceSession(db.Model):
    __tablename__ = 'attendance_sessions'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True)
    session_name = db.Column(db.String(120), nullable=False)
    session_number = db.Column(db.Integer, default=1, nullable=False)
    event_date = db.Column(db.Date, nullable=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    status = db.Column(db.String(30), default=AttendanceSessionStatus.UPCOMING, nullable=False, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    event = db.relationship('Event', back_populates='attendance_sessions')
    attendance_records = db.relationship('AttendanceRecord', back_populates='session', cascade='all, delete-orphan', lazy='dynamic')

    # Unique constraint per event session number
    __table_args__ = (
        db.UniqueConstraint('event_id', 'session_number', name='uq_event_session_number'),
    )

    @property
    def present_count(self):
        return self.attendance_records.filter_by(status='PRESENT').count()

    @property
    def total_records_count(self):
        return self.attendance_records.count()

    def is_time_active(self, current_dt=None):
        """
        Checks if current time falls within session start and end times if configured.
        Returns (is_active: bool, message: str)
        """
        if self.status == AttendanceSessionStatus.CANCELLED:
            return False, "This attendance session has been cancelled."
        if self.status == AttendanceSessionStatus.COMPLETED:
            return False, "This attendance session has already concluded."

        if not current_dt:
            current_dt = datetime.now()

        # If date is specified and doesn't match
        if self.event_date and current_dt.date() != self.event_date:
            return False, f"Session date is scheduled for {self.event_date.strftime('%b %d, %Y')}."

        current_time = current_dt.time()
        if self.start_time and current_time < self.start_time:
            return False, f"Session opens at {self.start_time.strftime('%I:%M %p')}."

        if self.end_time and current_time > self.end_time:
            return False, f"Session closed at {self.end_time.strftime('%I:%M %p')}."

        return True, "Session is active."

    def __repr__(self):
        return f'<AttendanceSession #{self.session_number} "{self.session_name}" (Event:{self.event_id})>'
