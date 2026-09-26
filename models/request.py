"""
Campus Flow - Organizer and Event Approval Request Models
Implements the Student Organizer Request system and the Mandatory Dual Event Approval System.
"""
from datetime import datetime
from .user import db

class OrganizerRequestStatus:
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'

    CHOICES = [PENDING, APPROVED, REJECTED]


class EventRequestStatus:
    PENDING_HOD_APPROVAL = 'pending_hod_approval'
    PENDING_DEAN_APPROVAL = 'pending_dean_approval'
    APPROVED = 'approved'
    REJECTED_BY_HOD = 'rejected_by_hod'
    REJECTED_BY_DEAN = 'rejected_by_dean'

    CHOICES = [
        PENDING_HOD_APPROVAL,
        PENDING_DEAN_APPROVAL,
        APPROVED,
        REJECTED_BY_HOD,
        REJECTED_BY_DEAN
    ]

    # Human-readable labels for badges and dashboards
    LABELS = {
        PENDING_HOD_APPROVAL: 'Waiting for HOD Approval',
        PENDING_DEAN_APPROVAL: 'HOD Approved — Waiting for Dean Approval',
        APPROVED: 'Approved and Published',
        REJECTED_BY_HOD: 'Rejected by HOD',
        REJECTED_BY_DEAN: 'Rejected by Dean'
    }

    BADGE_CLASSES = {
        PENDING_HOD_APPROVAL: 'bg-warning text-dark',
        PENDING_DEAN_APPROVAL: 'bg-info text-dark',
        APPROVED: 'bg-success text-white',
        REJECTED_BY_HOD: 'bg-danger text-white',
        REJECTED_BY_DEAN: 'bg-danger text-white'
    }


class OrganizerRequest(db.Model):
    __tablename__ = 'organizer_requests'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)
    reason = db.Column(db.Text, nullable=False)
    previous_experience = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(30), default=OrganizerRequestStatus.PENDING, nullable=False, index=True)
    reviewed_by_hod_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    decision_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    student = db.relationship('User', foreign_keys=[student_id], backref=db.backref('organizer_requests_submitted', lazy='dynamic'))
    department = db.relationship('CollegeDepartment', foreign_keys=[department_id])
    reviewed_by_hod = db.relationship('User', foreign_keys=[reviewed_by_hod_id])

    @property
    def status_label(self):
        if self.status == OrganizerRequestStatus.PENDING:
            return 'Waiting for HOD Approval'
        elif self.status == OrganizerRequestStatus.APPROVED:
            return 'Approved as Organizer'
        elif self.status == OrganizerRequestStatus.REJECTED:
            return 'Rejected'
        return self.status.capitalize()

    @property
    def badge_class(self):
        if self.status == OrganizerRequestStatus.PENDING:
            return 'bg-warning text-dark'
        elif self.status == OrganizerRequestStatus.APPROVED:
            return 'bg-success text-white'
        elif self.status == OrganizerRequestStatus.REJECTED:
            return 'bg-danger text-white'
        return 'bg-secondary text-white'

    def __repr__(self):
        return f'<OrganizerRequest {self.id} (Student: {self.student_id}, Dept: {self.department_id}, Status: {self.status})>'


class EventRequest(db.Model):
    __tablename__ = 'event_requests'

    id = db.Column(db.Integer, primary_key=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False, index=True)
    
    # Event metadata
    event_name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(100), nullable=False, default='Workshop')
    proposed_event_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    venue = db.Column(db.String(200), nullable=False)
    expected_participants = db.Column(db.Integer, default=100, nullable=False)
    registration_details = db.Column(db.Text, nullable=True)
    budget_requirements = db.Column(db.Text, nullable=True)
    additional_requirements = db.Column(db.Text, nullable=True)

    # Operational event configuration fields used to instantiate the Event record on approval
    registration_start_date = db.Column(db.DateTime, nullable=True)
    registration_deadline = db.Column(db.DateTime, nullable=True)
    registration_fee = db.Column(db.Float, default=0.0, nullable=False)
    is_free = db.Column(db.Boolean, default=True, nullable=False)
    poster_image = db.Column(db.String(500), nullable=True)
    rules = db.Column(db.Text, nullable=True)
    contact_info = db.Column(db.String(200), nullable=True)
    faculty_coordinator = db.Column(db.String(150), nullable=True)
    faculty_coordinator_contact = db.Column(db.String(100), nullable=True)
    allowed_departments = db.Column(db.String(255), default='ALL', nullable=False)
    allowed_years = db.Column(db.String(50), default='ALL', nullable=False)
    allowed_sections = db.Column(db.String(50), default='ALL', nullable=False)
    eligibility_notes = db.Column(db.String(255), nullable=True)
    registration_type = db.Column(db.String(20), default='INDIVIDUAL', nullable=False)
    min_team_size = db.Column(db.Integer, default=2, nullable=False)
    max_team_size = db.Column(db.Integer, default=4, nullable=False)
    team_payment_type = db.Column(db.String(20), default='FREE', nullable=False)
    require_full_team = db.Column(db.Boolean, default=False, nullable=False)
    upi_id = db.Column(db.String(100), nullable=True)
    upi_number = db.Column(db.String(20), nullable=True)
    upi_qr_image = db.Column(db.String(500), nullable=True)
    payment_instructions = db.Column(db.Text, nullable=True)
    enable_attendance = db.Column(db.Boolean, default=True, nullable=False)
    min_attendance_percentage = db.Column(db.Float, default=0.0, nullable=False)

    # HOD Approval Fields
    hod_reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    hod_approval_status = db.Column(db.String(30), default='pending', nullable=False)  # pending, approved, rejected
    hod_decision_at = db.Column(db.DateTime, nullable=True)
    hod_rejection_reason = db.Column(db.Text, nullable=True)

    # Dean Approval Fields
    dean_reviewer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    dean_approval_status = db.Column(db.String(30), default='pending', nullable=False) # pending, approved, rejected
    dean_decision_at = db.Column(db.DateTime, nullable=True)
    dean_rejection_reason = db.Column(db.Text, nullable=True)

    # General & Linkage Fields
    overall_status = db.Column(db.String(30), default=EventRequestStatus.PENDING_HOD_APPROVAL, nullable=False, index=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', use_alter=True), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    organizer = db.relationship('User', foreign_keys=[organizer_id], backref=db.backref('event_requests_submitted', lazy='dynamic'))
    department = db.relationship('CollegeDepartment', foreign_keys=[department_id])
    hod_reviewer = db.relationship('User', foreign_keys=[hod_reviewer_id])
    dean_reviewer = db.relationship('User', foreign_keys=[dean_reviewer_id])
    event = db.relationship('Event', foreign_keys=[event_id], backref=db.backref('creation_request', uselist=False))

    @property
    def is_dual_approved(self):
        """Backend dual approval validation check."""
        return (self.hod_approval_status == 'approved' and self.dean_approval_status == 'approved')

    # Field Aliases
    @property
    def registration_end_date(self):
        return self.registration_deadline

    @registration_end_date.setter
    def registration_end_date(self, value):
        self.registration_deadline = value

    @property
    def event_start_date(self):
        return self.start_time

    @event_start_date.setter
    def event_start_date(self, value):
        self.start_time = value

    @property
    def event_end_date(self):
        return self.end_time

    @event_end_date.setter
    def event_end_date(self, value):
        self.end_time = value

    @property
    def upi_qr_url(self):
        """Returns browser-accessible URL for organizer UPI QR, or None if unavailable."""
        from services.storage_service import get_media_url
        return get_media_url(self.upi_qr_image)

    @property
    def is_upi_qr_available(self):
        return bool(self.upi_qr_url)

    @property
    def poster_url(self):
        """Returns browser-accessible URL for event poster, or None if unavailable."""
        from services.storage_service import get_media_url
        return get_media_url(self.poster_image)

    @property
    def status_label(self):
        return EventRequestStatus.LABELS.get(self.overall_status, self.overall_status.replace('_', ' ').title())

    @property
    def badge_class(self):
        return EventRequestStatus.BADGE_CLASSES.get(self.overall_status, 'bg-secondary text-white')

    def __repr__(self):
        return f'<EventRequest {self.id} ({self.event_name}) - Status: {self.overall_status}>'
