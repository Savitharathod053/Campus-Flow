from datetime import datetime
import uuid
from .user import db

class CertificateStatus:
    MATCHED_AUTOMATICALLY = 'MATCHED_AUTOMATICALLY'
    PENDING_MANUAL_REVIEW = 'PENDING_MANUAL_REVIEW'
    ASSIGNED_MANUALLY = 'ASSIGNED_MANUALLY'
    UNMATCHED = 'UNMATCHED'
    DUPLICATE = 'DUPLICATE'
    INVALID = 'INVALID'

    # Aliases
    MATCHED = 'MATCHED_AUTOMATICALLY'
    MANUALLY_ASSIGNED = 'ASSIGNED_MANUALLY'

    CHOICES = [
        MATCHED_AUTOMATICALLY,
        PENDING_MANUAL_REVIEW,
        ASSIGNED_MANUALLY,
        UNMATCHED,
        DUPLICATE,
        INVALID
    ]


class Certificate(db.Model):
    __tablename__ = 'certificates'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    registration_id = db.Column(db.Integer, db.ForeignKey('event_registrations.id'), nullable=True)
    
    certificate_code = db.Column(db.String(64), unique=True, nullable=False, index=True)
    roll_number = db.Column(db.String(50), nullable=True, index=True)
    extracted_name = db.Column(db.String(150), nullable=True)
    confidence_score = db.Column(db.Float, default=0.0, nullable=True)
    file_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(20), default='pdf', nullable=False)  # 'pdf' or 'image'
    extracted_text = db.Column(db.Text, nullable=True)
    
    status = db.Column(db.String(50), default=CertificateStatus.UNMATCHED, nullable=False, index=True)
    assigned_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    upload_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    event = db.relationship('Event', back_populates='certificates')
    student = db.relationship('User', foreign_keys=[student_id])
    registration = db.relationship('EventRegistration', back_populates='certificates')
    assigned_by = db.relationship('User', foreign_keys=[assigned_by_id])

    @property
    def student_name(self):
        return self.student.name if self.student else None

    @property
    def event_name(self):
        return self.event.title if self.event else None

    @property
    def is_assigned(self):
        return self.status in (
            CertificateStatus.MATCHED_AUTOMATICALLY,
            CertificateStatus.ASSIGNED_MANUALLY,
            'MATCHED',
            'MANUALLY_ASSIGNED'
        ) and self.student_id is not None

    @property
    def status_label(self):
        labels = {
            CertificateStatus.MATCHED_AUTOMATICALLY: 'Matched Automatically',
            CertificateStatus.PENDING_MANUAL_REVIEW: 'Pending Manual Review',
            CertificateStatus.ASSIGNED_MANUALLY: 'Assigned Manually',
            CertificateStatus.UNMATCHED: 'Unmatched',
            CertificateStatus.DUPLICATE: 'Duplicate',
            CertificateStatus.INVALID: 'Invalid'
        }
        return labels.get(self.status, self.status)

    @property
    def is_pdf(self):
        return self.file_type.lower() == 'pdf' or self.file_path.lower().endswith('.pdf')

    @property
    def file_url(self):
        """Returns browser-accessible URL for certificate file (cloud or local)."""
        from services.storage_service import get_media_url
        return get_media_url(self.file_path)

    @property
    def certificate_image(self):
        # Compatibility property
        return self.file_path

    @certificate_image.setter
    def certificate_image(self, val):
        self.file_path = val
        if not self.original_filename and val:
            self.original_filename = val.split('/')[-1].split('\\')[-1]

    @property
    def issued_at(self):
        # Compatibility property
        return self.upload_date

    @issued_at.setter
    def issued_at(self, val):
        self.upload_date = val

    @staticmethod
    def generate_certificate_code(event_id, student_id=None):
        random_hash = uuid.uuid4().hex[:10].upper()
        s_part = f"-S{student_id}" if student_id else ""
        return f"CERT-CF-{datetime.utcnow().year}-E{event_id}{s_part}-{random_hash}"

    def __repr__(self):
        return f'<Certificate {self.certificate_code} ({self.status}) for Roll:{self.roll_number}>'
