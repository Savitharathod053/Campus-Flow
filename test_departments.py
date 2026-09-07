import unittest
from datetime import datetime, timedelta
from app import create_app
from config import Config
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile,
    Event, EventStatus, EventType, EventRegistrationType, Department
)

class DeptTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

class DepartmentTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(DeptTestConfig)
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_department_constants_and_order(self):
        """Verify the 8 canonical departments are defined and properly ordered."""
        expected_departments = ['CSE', 'IT', 'CSD', 'CSM', 'ECE', 'EEE', 'MECH', 'CIVILS']
        self.assertEqual(Department.ALL_CODES, expected_departments)
        
        # Verify CSD and CSM descriptions
        self.assertEqual(
            Department.CODE_TO_NAME['CSD'],
            'Computer Science and Engineering in Data Science (CSD)'
        )
        self.assertIn('AI and ML', Department.CODE_TO_NAME['CSM'])

    def test_department_normalization(self):
        """Test department code normalization including CIVIL -> CIVILS."""
        self.assertEqual(Department.normalize_code('cse'), 'CSE')
        self.assertEqual(Department.normalize_code('CIVIL'), 'CIVILS')
        self.assertEqual(Department.normalize_code('civils'), 'CIVILS')
        self.assertTrue(Department.is_valid('CSD'))
        self.assertTrue(Department.is_valid('csm'))
        self.assertTrue(Department.is_valid('civil'))

    def test_student_registration_for_all_departments(self):
        """Test that students from each of the 8 departments can register and have profiles created."""
        for idx, dept_code in enumerate(Department.ALL_CODES, start=1):
            email = f"student_{dept_code.lower()}@college.edu"
            roll = f"ROLL{idx:03d}{dept_code}"
            response = self.client.post('/auth/register/student', data={
                'name': f"Student {dept_code}",
                'email': email,
                'roll_number': roll,
                'department': dept_code,
                'year': '2',
                'section': 'A',
                'phone': f"+91 99000000{idx:02d}",
                'password': 'Password@123',
                'confirm_password': 'Password@123'
            }, follow_redirects=True)
            self.assertEqual(response.status_code, 200)

            user = User.query.filter_by(email=email).first()
            self.assertIsNotNone(user, f"User for {dept_code} should exist")
            self.assertIsNotNone(user.student_profile)
            self.assertEqual(user.student_profile.department, dept_code)

    def test_event_eligibility_with_new_departments(self):
        """Test event eligibility checks with CSD, CSM, and CIVILS/CIVIL compatibility."""
        # Create organizer
        org_user = User(name="Organizer", email="org@college.edu", role=UserRole.ORGANIZER, is_active=True)
        org_user.set_password("Pass@123")
        db.session.add(org_user)
        db.session.flush()

        # Event 1: Restricted to CSD, CSM
        event_ai_ds = Event(
            title="AI & Data Science Hackathon",
            slug="ai-ds-hackathon-2026",
            organizer_id=org_user.id,
            event_type=EventType.HACKATHON,
            department="CSD",
            faculty_coordinator="Dr. Coordinator",
            description="Hands-on coding hackathon in AI and Data Science",
            venue="Lab 4, Block B",
            start_time=datetime.utcnow() + timedelta(days=5),
            end_time=datetime.utcnow() + timedelta(days=6),
            registration_deadline=datetime.utcnow() + timedelta(days=4),
            status=EventStatus.APPROVED,
            allowed_departments="CSD,CSM"
        )
        # Event 2: Restricted to CIVIL (legacy string)
        event_civil = Event(
            title="Civil Conclave",
            slug="civil-conclave-2026",
            organizer_id=org_user.id,
            event_type=EventType.WORKSHOP,
            department="CIVILS",
            faculty_coordinator="Dr. Civil",
            description="National civil engineering technical workshop",
            venue="Civil Seminar Hall",
            start_time=datetime.utcnow() + timedelta(days=5),
            end_time=datetime.utcnow() + timedelta(days=6),
            registration_deadline=datetime.utcnow() + timedelta(days=4),
            status=EventStatus.APPROVED,
            allowed_departments="CIVIL"
        )
        db.session.add_all([event_ai_ds, event_civil])
        db.session.commit()

        # Student 1: CSD
        s_csd = StudentProfile(user_id=101, roll_number="CSD001", department="CSD", year=2, section="A")
        # Student 2: ECE
        s_ece = StudentProfile(user_id=102, roll_number="ECE001", department="ECE", year=2, section="A")
        # Student 3: CIVILS
        s_civils = StudentProfile(user_id=103, roll_number="CIV001", department="CIVILS", year=3, section="A")

        # Check eligibility for AI/DS event
        eligible_csd, _ = event_ai_ds.is_eligible(s_csd)
        eligible_ece, msg_ece = event_ai_ds.is_eligible(s_ece)
        self.assertTrue(eligible_csd)
        self.assertFalse(eligible_ece)
        self.assertIn("restricted to: CSD,CSM", msg_ece)

        # Check eligibility for CIVIL event: student has CIVILS, event has CIVIL
        eligible_civ, _ = event_civil.is_eligible(s_civils)
        self.assertTrue(eligible_civ)


if __name__ == '__main__':
    unittest.main()
