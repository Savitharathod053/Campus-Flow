from datetime import datetime
from .user import db

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    action = db.Column(db.String(60), nullable=False, index=True)
    target_type = db.Column(db.String(50), nullable=False, index=True)
    target_id = db.Column(db.Integer, nullable=True)
    target_name = db.Column(db.String(150), nullable=True)
    details = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    admin = db.relationship('User', back_populates='audit_logs', foreign_keys=[admin_id])

    def __repr__(self):
        return f'<AuditLog {self.action} on {self.target_type}:{self.target_id} by Admin:{self.admin_id}>'
