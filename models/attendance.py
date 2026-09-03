from datetime import datetime
from .user import db

class VerificationMethod:
    QR_SCAN = 'QR_SCAN'
    MANUAL = 'MANUAL'

    CHOICES = [QR_SCAN, MANUAL]


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('event_registrations.id', ondelete='CASCADE'), unique=True, nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    marked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    verification_method = db.Column(db.String(30), default=VerificationMethod.QR_SCAN, nullable=False)
    remarks = db.Column(db.String(255), nullable=True)

    # Relationships
    registration = db.relationship('EventRegistration', back_populates='attendance')
    event = db.relationship('Event', back_populates='attendance_records')
    student = db.relationship('User', foreign_keys=[student_id])
    marked_by = db.relationship('User', foreign_keys=[marked_by_id])

    def __repr__(self):
        return f'<AttendanceRecord Event:{self.event_id} Student:{self.student_id} at {self.scanned_at}>'


class AttendanceSession(db.Model):
    __tablename__ = 'attendance_sessions'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    session_name = db.Column(db.String(120), nullable=False)
    session_number = db.Column(db.Integer, default=1, nullable=False)
    event_date = db.Column(db.Date, nullable=True)
    start_time = db.Column(db.Time, nullable=True)
    end_time = db.Column(db.Time, nullable=True)
    status = db.Column(db.String(30), default='PENDING', nullable=False)  # PENDING, ACTIVE, COMPLETED
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    event = db.relationship('Event', backref=db.backref('attendance_sessions', lazy='dynamic', cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<AttendanceSession Event:{self.event_id} {self.session_name}>'

