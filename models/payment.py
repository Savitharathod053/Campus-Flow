from datetime import datetime
from .user import db


class PaymentStatus:
    PENDING = 'PENDING'
    TRANSACTION_ID_VERIFIED = 'TRANSACTION_ID_VERIFIED'
    PAYMENT_VERIFICATION_FAILED = 'PAYMENT_VERIFICATION_FAILED'
    VERIFIED = 'VERIFIED'
    REJECTED = 'REJECTED'
    MANUAL_REVIEW = 'MANUAL_REVIEW'

    # Aliases
    APPROVED = 'VERIFIED'
    PAYMENT_PENDING = 'PENDING'
    PAYMENT_APPROVED = 'VERIFIED'
    PAYMENT_REJECTED = 'REJECTED'
    SUCCESS = 'VERIFIED'
    FAILED = 'REJECTED'

    CHOICES = [
        PENDING,
        TRANSACTION_ID_VERIFIED,
        PAYMENT_VERIFICATION_FAILED,
        VERIFIED,
        REJECTED,
        MANUAL_REVIEW
    ]


class FraudRisk:
    LOW = 'LOW'
    MEDIUM = 'MEDIUM'
    HIGH = 'HIGH'

    CHOICES = [LOW, MEDIUM, HIGH]


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('event_registrations.id'), unique=True, nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='INR', nullable=False)
    expected_amount = db.Column(db.Float, nullable=True)
    detected_amount = db.Column(db.Float, nullable=True)
    
    transaction_id = db.Column(db.String(100), nullable=True, index=True)
    extracted_transaction_id = db.Column(db.String(100), nullable=True)
    payment_method = db.Column(db.String(50), nullable=True)  # UPI_QR, UPI_NUMBER, UPI_ID, etc.
    payment_screenshot = db.Column(db.String(255), nullable=True)
    screenshot_hash = db.Column(db.String(64), nullable=True, index=True)
    
    status = db.Column(db.String(50), default=PaymentStatus.PENDING, nullable=False, index=True)
    fraud_risk = db.Column(db.String(20), default=FraudRisk.LOW, nullable=True)
    fraud_details = db.Column(db.Text, nullable=True)
    ocr_extracted_data = db.Column(db.Text, nullable=True)
    verification_reason = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verified_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    registration = db.relationship('EventRegistration', back_populates='payment')
    team = db.relationship('Team', back_populates='payments')
    event = db.relationship('Event', backref=db.backref('payments', lazy='dynamic'))
    student = db.relationship('User', foreign_keys=[student_id], backref=db.backref('student_payments', lazy='dynamic'))
    organizer = db.relationship('User', foreign_keys=[organizer_id], backref=db.backref('organizer_payments', lazy='dynamic'))
    verified_by = db.relationship('User', foreign_keys=[verified_by_id])

    @property
    def payment_status(self):
        return self.status

    @payment_status.setter
    def payment_status(self, value):
        self.status = value

    @property
    def is_verified(self):
        return self.status in (PaymentStatus.VERIFIED, 'SUCCESS', 'APPROVED')

    @property
    def is_approved(self):
        return self.is_verified

    @property
    def is_pending(self):
        return self.status == PaymentStatus.PENDING

    @property
    def is_transaction_id_verified(self):
        return self.status == PaymentStatus.TRANSACTION_ID_VERIFIED

    @property
    def is_verification_failed(self):
        return self.status == PaymentStatus.PAYMENT_VERIFICATION_FAILED

    @property
    def is_rejected(self):
        return self.status in (PaymentStatus.REJECTED, 'FAILED')

    @property
    def is_manual_review(self):
        return self.status == PaymentStatus.MANUAL_REVIEW

    @property
    def status_label(self):
        labels = {
            PaymentStatus.PENDING: 'Payment Pending',
            PaymentStatus.TRANSACTION_ID_VERIFIED: 'Transaction ID Verified',
            PaymentStatus.PAYMENT_VERIFICATION_FAILED: 'Payment Verification Failed',
            PaymentStatus.VERIFIED: 'Payment Approved',
            PaymentStatus.REJECTED: 'Payment Rejected',
            PaymentStatus.MANUAL_REVIEW: 'Under Manual Review'
        }
        return labels.get(self.status, self.status)

    def __repr__(self):
        return f'<Payment {self.id} txn:{self.transaction_id} ({self.status}) - ₹{self.amount}>'
