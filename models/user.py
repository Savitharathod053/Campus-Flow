from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class UserRole:
    STUDENT = 'STUDENT'
    ORGANIZER = 'ORGANIZER'
    FACULTY_ADMIN = 'FACULTY_ADMIN'
    
    CHOICES = [STUDENT, ORGANIZER, FACULTY_ADMIN]


class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    role = db.Column(db.String(20), nullable=False, default=UserRole.STUDENT, index=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    student_profile = db.relationship('StudentProfile', back_populates='user', uselist=False, cascade='all, delete-orphan')
    organizer_profile = db.relationship('OrganizerProfile', back_populates='user', foreign_keys='OrganizerProfile.user_id', uselist=False, cascade='all, delete-orphan')
    faculty_profile = db.relationship('FacultyProfile', back_populates='user', uselist=False, cascade='all, delete-orphan')
    
    organized_events = db.relationship('Event', back_populates='organizer', lazy='dynamic', cascade='all, delete-orphan')
    registrations = db.relationship('EventRegistration', back_populates='student', lazy='dynamic', cascade='all, delete-orphan')
    announcements = db.relationship('Announcement', back_populates='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
        
    @property
    def is_student(self):
        return self.role == UserRole.STUDENT
        
    @property
    def is_organizer(self):
        return self.role == UserRole.ORGANIZER
        
    @property
    def is_admin(self):
        return self.role == UserRole.FACULTY_ADMIN
        
    def __repr__(self):
        return f'<User {self.email} ({self.role})>'


class StudentProfile(db.Model):
    __tablename__ = 'student_profiles'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    department = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=False)  # 1, 2, 3, 4
    section = db.Column(db.String(10), nullable=False)
    college_id_card = db.Column(db.String(255), nullable=True)
    
    user = db.relationship('User', back_populates='student_profile')
    
    def __repr__(self):
        return f'<StudentProfile {self.roll_number} - {self.department}>'


class OrganizerProfile(db.Model):
    __tablename__ = 'organizer_profiles'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    organization_name = db.Column(db.String(150), nullable=False)  # e.g., "Google Developer Student Club", "CSI Student Chapter"
    department = db.Column(db.String(100), nullable=False)        # Department: CSE, ECE, MECH, IT, CIVIL, EEE, General
    designation = db.Column(db.String(100), nullable=True)        # e.g., "Lead Organizer", "President"
    
    # Approval fields
    is_verified = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default='PENDING', nullable=False)  # PENDING, APPROVED, REJECTED
    rejection_reason = db.Column(db.String(255), nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', back_populates='organizer_profile', foreign_keys=[user_id])
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    
    def __repr__(self):
        return f'<OrganizerProfile {self.organization_name} ({self.status})>'


class FacultyProfile(db.Model):
    __tablename__ = 'faculty_profiles'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False)
    employee_id = db.Column(db.String(50), unique=True, nullable=False)
    department = db.Column(db.String(100), nullable=False)       # CSE, ECE, MECH, IT, CIVIL, EEE, General
    designation = db.Column(db.String(100), nullable=False)     # e.g., "Head of Department & Faculty Admin", "Dean"
    
    user = db.relationship('User', back_populates='faculty_profile')
    
    def __repr__(self):
        return f'<FacultyProfile {self.employee_id} - {self.department}>'
