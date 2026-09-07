from .auth import auth_bp
from .public import public_bp
from .student import student_bp
from .organizer import organizer_bp
from .admin import admin_bp
from .payment import payment_bp
from .certificates import cert_bp
from .faculty import faculty_bp
from .hod import hod_bp
from .dean import dean_bp

__all__ = [
    'auth_bp',
    'public_bp',
    'student_bp',
    'organizer_bp',
    'admin_bp',
    'payment_bp',
    'cert_bp',
    'faculty_bp',
    'hod_bp',
    'dean_bp'
]
