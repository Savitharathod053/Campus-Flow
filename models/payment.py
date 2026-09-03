from datetime import datetime
from .user import db

class PaymentStatus:
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'

    CHOICES = [PENDING, SUCCESS, FAILED]


class Payment(db.Model):
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('event_registrations.id', ondelete='CASCADE'), unique=True, nullable=False)
    
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default='INR', nullable=False)
    
    razorpay_order_id = db.Column(db.String(100), nullable=True, index=True)
    razorpay_payment_id = db.Column(db.String(100), nullable=True, index=True)
    razorpay_signature = db.Column(db.String(255), nullable=True)
    
    status = db.Column(db.String(20), default=PaymentStatus.PENDING, nullable=False, index=True)
    payment_method = db.Column(db.String(50), nullable=True)  # UPI, CARD, NETBANKING, SANDBOX_SIMULATED
    notes = db.Column(db.Text, nullable=True)
    team_id = db.Column(db.Integer, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    registration = db.relationship('EventRegistration', back_populates='payment')

    def __repr__(self):
        return f'<Payment {self.razorpay_order_id} ({self.status}) - ₹{self.amount}>'
