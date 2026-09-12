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
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True)

    # Unique constraint: student cannot register more than once for same event
    __table_args__ = (
        db.UniqueConstraint('event_id', 'student_id', name='uq_event_student_registration'),
    )

    # Relationships
    event = db.relationship('Event', back_populates='registrations')
    student = db.relationship('User', back_populates='registrations')
    team = db.relationship('Team', back_populates='registrations')
    custom_responses = db.relationship('CustomFieldResponse', back_populates='registration', cascade='all, delete-orphan')
    payment = db.relationship('Payment', back_populates='registration', uselist=False, cascade='all, delete-orphan')
    attendance_records = db.relationship('AttendanceRecord', back_populates='registration', cascade='all, delete-orphan')
    certificates = db.relationship('Certificate', back_populates='registration', cascade='all, delete-orphan')

    @property
    def certificate(self):
        for c in self.certificates:
            if getattr(c, 'is_assigned', False):
                return c
        return None

    @property
    def is_confirmed(self):
        return self.status == RegistrationStatus.CONFIRMED

    @property
    def is_paid(self):
        if not self.event or self.event.is_free or (self.event.registration_fee or 0) == 0:
            return True
        if self.payment and self.payment.status in ['VERIFIED', 'SUCCESS', 'PAID', 'COMPLETED']:
            return True
        if self.team and (self.team.payment_status in ['PAID', 'SUCCESS'] or getattr(self.team, 'is_paid', False)):
            return True
        return False

    @property
    def payment_badge_info(self):
        """Returns structured payment status info for student dashboard and event lists."""
        if not self.event or self.event.is_free or (self.event.registration_fee or 0) == 0:
            return {
                'code': 'FREE',
                'label': 'Free Event',
                'badge_class': 'bg-light text-success border',
                'icon': 'bi-check-circle',
                'message': 'No fee required'
            }
        
        if self.payment:
            st = self.payment.status
            if st in ('VERIFIED', 'SUCCESS'):
                return {
                    'code': 'VERIFIED',
                    'label': 'Payment Approved',
                    'badge_class': 'bg-success',
                    'icon': 'bi-check2-circle',
                    'message': 'Ticket Available'
                }
            elif st == 'TRANSACTION_ID_VERIFIED':
                return {
                    'code': 'TRANSACTION_ID_VERIFIED',
                    'label': 'Transaction ID Verified',
                    'badge_class': 'bg-info text-dark',
                    'icon': 'bi-shield-check',
                    'message': 'Awaiting organizer confirmation'
                }
            elif st == 'PAYMENT_VERIFICATION_FAILED':
                return {
                    'code': 'PAYMENT_VERIFICATION_FAILED',
                    'label': 'Payment Verification Failed',
                    'badge_class': 'bg-danger',
                    'icon': 'bi-exclamation-octagon-fill',
                    'message': 'Transaction ID mismatch. Please check and re-upload.'
                }
            elif st == 'MANUAL_REVIEW':
                return {
                    'code': 'MANUAL_REVIEW',
                    'label': 'Payment Under Manual Review',
                    'badge_class': 'bg-warning text-dark',
                    'icon': 'bi-shield-exclamation',
                    'message': 'Organizer manual review in progress'
                }
            elif st in ('REJECTED', 'FAILED'):
                return {
                    'code': 'REJECTED',
                    'label': 'Payment Rejected',
                    'badge_class': 'bg-danger',
                    'icon': 'bi-x-circle-fill',
                    'message': self.payment.verification_reason or 'Payment verification failed.'
                }
            else:
                return {
                    'code': 'PENDING',
                    'label': 'Payment Pending',
                    'badge_class': 'bg-warning text-dark',
                    'icon': 'bi-hourglass-split',
                    'message': 'Verification pending organizer approval'
                }

        return {
            'code': 'NOT_SUBMITTED',
            'label': 'Payment Pending',
            'badge_class': 'bg-warning text-dark',
            'icon': 'bi-credit-card',
            'message': 'Proof not yet submitted'
        }

    @property
    def payment_status_display(self):
        if not self.event or self.event.is_free or (self.event.registration_fee or 0) == 0 or getattr(self.event, 'team_payment_type', None) == 'FREE':
            return 'Free'
        if self.payment:
            if self.payment.status in ('VERIFIED', 'SUCCESS'):
                return 'Payment Approved'
            elif self.payment.status == 'TRANSACTION_ID_VERIFIED':
                return 'Transaction ID Verified'
            elif self.payment.status == 'PAYMENT_VERIFICATION_FAILED':
                return 'Payment Verification Failed'
            elif self.payment.status == 'MANUAL_REVIEW':
                return 'Under Review'
            elif self.payment.status in ('REJECTED', 'FAILED'):
                return 'Payment Rejected'
            elif self.payment.status == 'PENDING':
                return 'Payment Pending'
        if self.is_paid:
            return 'Paid'
        return 'Pending'

    @property
    def attendance(self):
        """Backward-compatible property returning the first/primary attendance record."""
        return self.attendance_records[0] if self.attendance_records else None

    @property
    def is_attended(self):
        """Returns True if student has attended at least one session."""
        return any(r.status == 'PRESENT' for r in self.attendance_records)

    @property
    def attended_sessions_count(self):
        return len([r for r in self.attendance_records if r.status == 'PRESENT'])

    @property
    def attendance_percentage(self):
        total = self.event.total_sessions_count if self.event else 1
        if total == 0:
            return 100.0 if self.is_attended else 0.0
        return round((self.attended_sessions_count / total) * 100.0, 2)

    @property
    def is_attendance_requirement_met(self):
        if not self.event:
            return self.is_attended
        return self.event.is_student_attendance_satisfied(self.student_id)

    @property
    def has_certificate(self):
        return self.certificate is not None

    @staticmethod
    def generate_registration_code(event_id, student_id):
        random_suffix = uuid.uuid4().hex[:8].upper()
        return f"CF-E{event_id}-S{student_id}-{random_suffix}"

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
