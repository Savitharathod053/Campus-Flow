from datetime import datetime
from .user import db

class VerificationMethod:
    QR_SCAN = 'QR_SCAN'
    MANUAL = 'MANUAL'

    CHOICES = [QR_SCAN, MANUAL]


class AttendanceStatus:
    PRESENT = 'PRESENT'
    ABSENT = 'ABSENT'
    EXCUSED = 'EXCUSED'

    CHOICES = [PRESENT, ABSENT, EXCUSED]


class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('event_registrations.id', ondelete='CASCADE'), nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    session_id = db.Column(db.Integer, db.ForeignKey('attendance_sessions.id'), nullable=True, index=True)
    marked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    scanned_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    verification_method = db.Column(db.String(30), default=VerificationMethod.QR_SCAN, nullable=False)
    status = db.Column(db.String(20), default=AttendanceStatus.PRESENT, nullable=False)
    remarks = db.Column(db.String(255), nullable=True)

    # Unique constraint preventing duplicate attendance for same student in the same session
    __table_args__ = (
        db.UniqueConstraint('event_id', 'session_id', 'student_id', name='uq_event_session_student_attendance'),
    )

    # Relationships
    registration = db.relationship('EventRegistration', back_populates='attendance_records')
    event = db.relationship('Event', back_populates='attendance_records')
    session = db.relationship('AttendanceSession', back_populates='attendance_records')
    student = db.relationship('User', foreign_keys=[student_id])
    marked_by = db.relationship('User', foreign_keys=[marked_by_id])

    @property
    def is_present(self):
        return self.status == AttendanceStatus.PRESENT

    def __repr__(self):
        return f'<AttendanceRecord Event:{self.event_id} Session:{self.session_id} Student:{self.student_id} Status:{self.status} at {self.scanned_at}>'

