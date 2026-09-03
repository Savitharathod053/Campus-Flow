from datetime import datetime
import uuid
from .user import db

class RegistrationStatus:
    PENDING_PAYMENT = 'PENDING_PAYMENT'
    CONFIRMED = 'CONFIRMED'
    CANCELLED = 'CANCELLED'

    CHOICES = [PENDING_PAYMENT, CONFIRMED, CANCELLED]


class EventRegistration(db.Model):
    __tablename__ = 'event_registrations'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    registration_code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    qr_code_image = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(30), default=RegistrationStatus.PENDING_PAYMENT, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True)

    # Unique constraint: student cannot register more than once for same event
    __table_args__ = (
        db.UniqueConstraint('event_id', 'student_id', name='uq_event_student_registration'),
    )

    # Relationships
    event = db.relationship('Event', back_populates='registrations')
    student = db.relationship('User', back_populates='registrations')
    custom_responses = db.relationship('CustomFieldResponse', back_populates='registration', cascade='all, delete-orphan')
    payment = db.relationship('Payment', back_populates='registration', uselist=False, cascade='all, delete-orphan')
    attendance = db.relationship('AttendanceRecord', back_populates='registration', uselist=False, cascade='all, delete-orphan')
    certificate = db.relationship('Certificate', back_populates='registration', uselist=False, cascade='all, delete-orphan')

    @property
    def is_confirmed(self):
        return self.status == RegistrationStatus.CONFIRMED

    @property
    def is_attended(self):
        return self.attendance is not None

    @property
    def has_certificate(self):
        return self.certificate is not None

    @staticmethod
    def generate_registration_code(event_id, student_id):
        random_suffix = uuid.uuid4().hex[:8].upper()
        return f"FF-E{event_id}-S{student_id}-{random_suffix}"

    def __repr__(self):
        return f'<EventRegistration {self.registration_code} ({self.status})>'


class CustomFieldResponse(db.Model):
    __tablename__ = 'custom_field_responses'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('event_registrations.id', ondelete='CASCADE'), nullable=False)
    field_id = db.Column(db.Integer, db.ForeignKey('custom_registration_fields.id'), nullable=False)
    field_value = db.Column(db.Text, nullable=True)

    registration = db.relationship('EventRegistration', back_populates='custom_responses')
    field = db.relationship('CustomRegistrationField', back_populates='responses')

    def __repr__(self):
        return f'<CustomFieldResponse Field:{self.field_id} Val:{self.field_value}>'
