"""
Campus Flow - Department Definitions & Database Model
"""
from datetime import datetime
from .user import db

class CollegeDepartment(db.Model):
    __tablename__ = 'departments'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    hod_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    hod = db.relationship('User', foreign_keys=[hod_id])

    def __repr__(self):
        return f'<CollegeDepartment {self.code} - {self.name}>'


class Department:
    CSE = 'CSE'
    IT = 'IT'
    CSD = 'CSD'
    CSM = 'CSM'
    ECE = 'ECE'
    EEE = 'EEE'
    MECH = 'MECH'
    CIVILS = 'CIVILS'

    # Ordered list of (code, display_name)
    CHOICES = [
        ('CSE', 'Computer Science & Engineering (CSE)'),
        ('IT', 'Information Technology (IT)'),
        ('CSD', 'Computer Science and Engineering in Data Science (CSD)'),
        ('CSM', 'Computer Science and Engineering in AI and ML (CSM)'),
        ('ECE', 'Electronics & Communication Engineering (ECE)'),
        ('EEE', 'Electrical & Electronics Engineering (EEE)'),
        ('MECH', 'Mechanical Engineering (MECH)'),
        ('CIVILS', 'Civil Engineering (CIVILS)'),
    ]

    ALL_CODES = [code for code, _ in CHOICES]
    ALL_NAMES = [name for _, name in CHOICES]
    CODE_TO_NAME = dict(CHOICES)

    @classmethod
    def normalize_code(cls, code: str) -> str:
        """
        Normalizes a department code or variant to its canonical uppercase representation.
        Handles aliases like 'CIVIL' -> 'CIVILS'.
        """
        if not code:
            return ''
        upper = code.strip().upper()
        if upper == 'CIVIL':
            return cls.CIVILS
        return upper

    @classmethod
    def is_valid(cls, code: str) -> bool:
        """Check if code is one of the 8 canonical departments or aliases."""
        return cls.normalize_code(code) in cls.ALL_CODES

    @classmethod
    def get_all_active(cls):
        """Returns list of active departments from database, falling back to static CHOICES."""
        try:
            depts = CollegeDepartment.query.filter_by(is_active=True).order_by(CollegeDepartment.id.asc()).all()
            if depts:
                return [(d.code, f"{d.name} ({d.code})") for d in depts]
        except Exception:
            pass
        return cls.CHOICES
