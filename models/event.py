from datetime import datetime
import re
from .user import db

class EventStatus:
    DRAFT = 'DRAFT'
    PENDING_APPROVAL = 'PENDING_APPROVAL'
    APPROVED = 'APPROVED'
    REGISTRATION_OPEN = 'REGISTRATION_OPEN'
    REGISTRATION_CLOSED = 'REGISTRATION_CLOSED'
    EVENT_COMPLETED = 'EVENT_COMPLETED'
    REJECTED = 'REJECTED'
    CANCELLED = 'CANCELLED'

    CHOICES = [
        DRAFT, PENDING_APPROVAL, APPROVED, 
        REGISTRATION_OPEN, REGISTRATION_CLOSED, 
        EVENT_COMPLETED, REJECTED, CANCELLED
    ]


class EventType:
    WORKSHOP = 'Workshop'
    HACKATHON = 'Hackathon'
    SEMINAR = 'Seminar'
    CULTURAL = 'Cultural'
    TECHNICAL = 'Technical'
    SPORTS = 'Sports'
    CLUB = 'Club Activity'
    SYMPOSIUM = 'Symposium'

    CHOICES = [WORKSHOP, HACKATHON, SEMINAR, CULTURAL, TECHNICAL, SPORTS, CLUB, SYMPOSIUM]


class Event(db.Model):
    __tablename__ = 'events'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False, index=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    # Event metadata
    event_type = db.Column(db.String(50), nullable=False, default=EventType.WORKSHOP)
    department = db.Column(db.String(100), nullable=False)  # Organizing Department
    faculty_coordinator = db.Column(db.String(150), nullable=False)
    faculty_coordinator_contact = db.Column(db.String(100), nullable=True)
    contact_info = db.Column(db.String(200), nullable=True)
    
    # Eligibility rules
    allowed_departments = db.Column(db.String(255), default='ALL', nullable=False)  # 'ALL' or comma-separated: 'CSE,ECE,IT'
    allowed_years = db.Column(db.String(50), default='ALL', nullable=False)          # 'ALL' or comma-separated: '1,2,3,4'
    allowed_sections = db.Column(db.String(50), default='ALL', nullable=False)       # 'ALL' or comma-separated: 'A,B,C'
    eligibility_notes = db.Column(db.String(255), nullable=True)
    
    # Content & Media
    description = db.Column(db.Text, nullable=False)
    rules = db.Column(db.Text, nullable=True)
    poster_image = db.Column(db.String(255), nullable=True)
    venue = db.Column(db.String(150), nullable=False)
    
    # Timing
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    registration_deadline = db.Column(db.DateTime, nullable=False)
    
    # Capacity & Pricing
    max_participants = db.Column(db.Integer, default=100, nullable=False)
    registration_fee = db.Column(db.Float, default=0.0, nullable=False)
    is_free = db.Column(db.Boolean, default=True, nullable=False)
    
    # Team Registration Settings (matching database schema)
    registration_type = db.Column(db.String(20), default='INDIVIDUAL', nullable=False)  # 'INDIVIDUAL' or 'TEAM'
    min_team_size = db.Column(db.Integer, default=2, nullable=False)
    max_team_size = db.Column(db.Integer, default=4, nullable=False)
    team_payment_type = db.Column(db.String(20), default='FREE', nullable=False)        # 'FREE' or 'PER_TEAM' or 'PER_MEMBER'
    require_full_team = db.Column(db.Boolean, default=False, nullable=False)

    # Attendance Settings (matching database schema)
    enable_attendance = db.Column(db.Boolean, default=True, nullable=False)
    min_attendance_percentage = db.Column(db.Float, default=0.0, nullable=False)

    # Lifecycle Status
    status = db.Column(db.String(30), default=EventStatus.PENDING_APPROVAL, nullable=False, index=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    organizer = db.relationship('User', back_populates='organized_events')
    custom_fields = db.relationship('CustomRegistrationField', back_populates='event', cascade='all, delete-orphan', order_by='CustomRegistrationField.display_order')
    registrations = db.relationship('EventRegistration', back_populates='event', cascade='all, delete-orphan', lazy='dynamic')
    announcements = db.relationship('Announcement', back_populates='event', cascade='all, delete-orphan', order_by='Announcement.created_at.desc()')
    attendance_records = db.relationship('AttendanceRecord', back_populates='event', cascade='all, delete-orphan')
    certificates = db.relationship('Certificate', back_populates='event', cascade='all, delete-orphan')

    @property
    def confirmed_registrations_count(self):
        return self.registrations.filter_by(status='CONFIRMED').count()

    @property
    def available_seats(self):
        count = self.confirmed_registrations_count
        return max(0, self.max_participants - count)

    @property
    def is_full(self):
        return self.available_seats <= 0

    @property
    def is_deadline_passed(self):
        return datetime.utcnow() > self.registration_deadline

    @property
    def is_live_registration_open(self):
        if self.status not in (EventStatus.APPROVED, EventStatus.REGISTRATION_OPEN):
            return False
        if self.is_deadline_passed:
            return False
        if self.is_full:
            return False
        return True

    def check_student_eligibility(self, student_profile):
        """Validates whether a given student profile can register for this event."""
        if not student_profile:
            return False, "Student profile required."
            
        if self.allowed_departments != 'ALL':
            allowed_dept_list = [d.strip().upper() for d in self.allowed_departments.split(',')]
            if student_profile.department.strip().upper() not in allowed_dept_list:
                return False, f"This event is restricted to: {self.allowed_departments} department(s)."
                
        if self.allowed_years != 'ALL':
            allowed_year_list = [y.strip() for y in self.allowed_years.split(',')]
            if str(student_profile.year).strip() not in allowed_year_list:
                return False, f"This event is restricted to Year: {self.allowed_years}."
                
        if self.allowed_sections != 'ALL':
            allowed_sec_list = [s.strip().upper() for s in self.allowed_sections.split(',')]
            if student_profile.section.strip().upper() not in allowed_sec_list:
                return False, f"This event is restricted to Section: {self.allowed_sections}."
                
        return True, "Eligible"

    @staticmethod
    def generate_slug(title):
        base_slug = re.sub(r'[^a-zA-Z0-9]+', '-', title.lower()).strip('-')
        timestamp = int(datetime.utcnow().timestamp())
        return f"{base_slug}-{timestamp}"

    def __repr__(self):
        return f'<Event {self.title} ({self.status})>'


class CustomRegistrationField(db.Model):
    __tablename__ = 'custom_registration_fields'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id', ondelete='CASCADE'), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)  # machine key, e.g. team_name
    field_label = db.Column(db.String(200), nullable=False) # display label, e.g. Team Name
    field_type = db.Column(db.String(30), default='text', nullable=False) # text, number, select, textarea, url, checkbox
    is_required = db.Column(db.Boolean, default=False, nullable=False)
    options_csv = db.Column(db.String(500), nullable=True) # for 'select' type: "Veg, Non-Veg, Vegan"
    display_order = db.Column(db.Integer, default=0, nullable=False)

    event = db.relationship('Event', back_populates='custom_fields')
    responses = db.relationship('CustomFieldResponse', back_populates='field', cascade='all, delete-orphan')

    def get_options_list(self):
        if not self.options_csv:
            return []
        return [opt.strip() for opt in self.options_csv.split(',') if opt.strip()]

    def __repr__(self):
        return f'<CustomField {self.field_name} ({self.field_type})>'
