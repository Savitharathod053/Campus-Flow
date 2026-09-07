"""
Campus Flow - Database Backup Utility
Safely exports and backs up existing database records before maintenance or resets.
"""

import os
import json
from datetime import datetime
from pathlib import Path
from app import create_app
from models import (
    db, User, StudentProfile, OrganizerProfile, FacultyProfile,
    Event, CustomRegistrationField, EventRegistration, CustomFieldResponse,
    Payment, AttendanceRecord, Announcement, Certificate
)

BASE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = BASE_DIR / 'backups'

def backup_database():
    app = create_app()
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    backup_file = BACKUP_DIR / f"campus_flow_backup_{timestamp}.json"

    with app.app_context():
        print(f"Creating database backup to {backup_file}...")
        data = {
            'metadata': {
                'timestamp': datetime.utcnow().isoformat(),
                'version': 'Campus Flow 1.0 Production'
            },
            'users': [],
            'student_profiles': [],
            'organizer_profiles': [],
            'faculty_profiles': [],
            'events': [],
            'custom_fields': [],
            'registrations': [],
            'custom_responses': [],
            'payments': [],
            'attendance_records': [],
            'announcements': [],
            'certificates': []
        }

        try:
            for u in User.query.all():
                data['users'].append({
                    'id': u.id,
                    'email': u.email,
                    'name': u.name,
                    'phone': u.phone,
                    'role': u.role,
                    'is_active': u.is_active,
                    'created_at': u.created_at.isoformat() if u.created_at else None
                })

            for sp in StudentProfile.query.all():
                data['student_profiles'].append({
                    'id': sp.id,
                    'user_id': sp.user_id,
                    'roll_number': sp.roll_number,
                    'department': sp.department,
                    'year': sp.year,
                    'section': sp.section
                })

            for op in OrganizerProfile.query.all():
                data['organizer_profiles'].append({
                    'id': op.id,
                    'user_id': op.user_id,
                    'organization_name': op.organization_name,
                    'department': op.department,
                    'designation': op.designation,
                    'is_verified': op.is_verified,
                    'status': op.status
                })

            for fp in FacultyProfile.query.all():
                data['faculty_profiles'].append({
                    'id': fp.id,
                    'user_id': fp.user_id,
                    'department': fp.department,
                    'employee_id': fp.employee_id,
                    'designation': fp.designation
                })

            for ev in Event.query.all():
                data['events'].append({
                    'id': ev.id,
                    'title': ev.title,
                    'slug': ev.slug,
                    'organizer_id': ev.organizer_id,
                    'event_type': ev.event_type,
                    'department': ev.department,
                    'venue': ev.venue,
                    'start_time': ev.start_time.isoformat() if ev.start_time else None,
                    'end_time': ev.end_time.isoformat() if ev.end_time else None,
                    'status': ev.status
                })

            for reg in EventRegistration.query.all():
                data['registrations'].append({
                    'id': reg.id,
                    'event_id': reg.event_id,
                    'student_id': reg.student_id,
                    'registration_code': reg.registration_code,
                    'status': reg.status,
                    'created_at': reg.created_at.isoformat() if reg.created_at else None
                })

            for cert in Certificate.query.all():
                data['certificates'].append({
                    'id': cert.id,
                    'event_id': cert.event_id,
                    'student_id': cert.student_id,
                    'certificate_code': cert.certificate_code,
                    'roll_number': cert.roll_number,
                    'status': cert.status,
                    'file_path': cert.file_path,
                    'original_filename': cert.original_filename
                })

            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            print(f"Database backup saved successfully ({len(data['users'])} users, {len(data['events'])} events, {len(data['registrations'])} registrations).")
            return str(backup_file)

        except Exception as e:
            print(f"Warning/Error during backup: {e}")
            with open(backup_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return str(backup_file)


if __name__ == '__main__':
    backup_database()
