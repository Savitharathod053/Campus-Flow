from datetime import datetime
import uuid
from .user import db

class CertificateStatus:
    MATCHED = 'MATCHED'
    UNMATCHED = 'UNMATCHED'
    DUPLICATE = 'DUPLICATE'
    INVALID = 'INVALID'
    MANUALLY_ASSIGNED = 'MANUALLY_ASSIGNED'

    CHOICES = [MATCHED, UNMATCHED, DUPLICATE, INVALID, MANUALLY_ASSIGNED]


class Certificate(db.Model):
    __tablename__ = 'certificates'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('event_registrations.id'), nullable=True)
    
    certificate_code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    roll_number = db.Column(db.String(50), nullable=True, index=True)
    file_path = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(20), default='pdf', nullable=False)  # 'pdf' or 'image'
    extracted_text = db.Column(db.Text, nullable=True)
    
    status = db.Column(db.String(30), default=CertificateStatus.UNMATCHED, nullable=False, index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    upload_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    event = db.relationship('Event', back_populates='certificates')
    student = db.relationship('User', foreign_keys=[student_id])
    registration = db.relationship('EventRegistration', back_populates='certificate')
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])

    @property
    def is_assigned(self):
        return self.status in (CertificateStatus.MATCHED, CertificateStatus.MANUALLY_ASSIGNED) and self.student_id is not None

    @property
    def is_pdf(self):
        return self.file_type.lower() == 'pdf' or self.file_path.lower().endswith('.pdf')

    @property
    def certificate_image(self):
        # Compatibility property
        return self.file_path

    @property
    def issued_at(self):
        # Compatibility property
        return self.upload_date

    @staticmethod
    def generate_certificate_code(event_id, student_id=None):
        random_hash = uuid.uuid4().hex[:10].upper()
        s_part = f"-S{student_id}" if student_id else ""
        return f"CERT-FF-{datetime.utcnow().year}-E{event_id}{s_part}-{random_hash}"

    def __repr__(self):
        return f'<Certificate {self.certificate_code} ({self.status}) for Roll:{self.roll_number}>'
