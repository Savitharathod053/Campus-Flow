from datetime import datetime, timedelta
from app import create_app
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile, FacultyProfile,
    Event, EventStatus, EventType, CustomRegistrationField,
    EventRegistration, RegistrationStatus, CustomFieldResponse,
    Payment, PaymentStatus, AttendanceRecord, VerificationMethod,
    Announcement, Certificate
)
from services.qr_service import generate_ticket_qr
from services.cert_service import generate_certificate_image

def seed_database():
    app = create_app()
    with app.app_context():
        print("Cleaning and seeding database...")
        db.drop_all()
        db.create_all()

        # ----------------------------------------------------
        # 1. CREATE FACULTY ADMINS FOR DIFFERENT DEPARTMENTS
        # ----------------------------------------------------
        # Central Dean / Super Admin
        admin_dean = User(
            name="Dr. S. K. Narayanan",
            email="admin@college.edu",
            phone="+91 9840112233",
            role=UserRole.FACULTY_ADMIN,
            is_active=True
        )
        admin_dean.set_password("Pass@123")
        db.session.add(admin_dean)
        db.session.flush()

        fp_dean = FacultyProfile(
            user_id=admin_dean.id,
            employee_id="FAC-GEN-001",
            department="General",
            designation="Dean of Student Affairs & Chief Admin"
        )
        db.session.add(fp_dean)

        # Department Admins
        dept_admins_data = [
            ("Dr. K. Ramanathan", "admin.cse@college.edu", "FAC-CSE-101", "CSE", "Head of Dept & Faculty Admin (CSE)", "+91 9840112244"),
            ("Dr. H. V. Venkatesh", "admin.ece@college.edu", "FAC-ECE-102", "ECE", "Professor & Faculty Admin (ECE)", "+91 9840112255"),
            ("Prof. Meenakshi Sundaram", "admin.it@college.edu", "FAC-IT-103", "IT", "Associate Professor & Faculty Admin (IT)", "+91 9840112266"),
            ("Dr. R. Ramesh", "admin.mech@college.edu", "FAC-MECH-104", "MECH", "Professor & Faculty Admin (MECH)", "+91 9840112277")
        ]

        for name, email, empid, dept, desig, phone in dept_admins_data:
            adm_u = User(
                name=name,
                email=email,
                phone=phone,
                role=UserRole.FACULTY_ADMIN,
                is_active=True
            )
            adm_u.set_password("Pass@123")
            db.session.add(adm_u)
            db.session.flush()

            adm_fp = FacultyProfile(
                user_id=adm_u.id,
                employee_id=empid,
                department=dept,
                designation=desig
            )
            db.session.add(adm_fp)

        # ----------------------------------------------------
        # 2. CREATE ORGANIZERS (APPROVED & PENDING)
        # ----------------------------------------------------
        # Approved Organizer 1 (CSE Club)
        org_user1 = User(
            name="Priya Patel",
            email="organizer@college.edu",
            phone="+91 9876501234",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        org_user1.set_password("Pass@123")
        db.session.add(org_user1)
        db.session.flush()

        org_prof1 = OrganizerProfile(
            user_id=org_user1.id,
            organization_name="ACM Student Chapter & Coding Club",
            department="CSE",
            designation="President & Student Lead",
            is_verified=True,
            status="APPROVED",
            approved_by_id=admin_dean.id,
            approved_at=datetime.utcnow() - timedelta(days=30)
        )
        db.session.add(org_prof1)

        # Approved Organizer 2 (ECE Club)
        org_user2 = User(
            name="Arun Verma",
            email="robotics.club@college.edu",
            phone="+91 9876505678",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        org_user2.set_password("Pass@123")
        db.session.add(org_user2)
        db.session.flush()

        org_prof2 = OrganizerProfile(
            user_id=org_user2.id,
            organization_name="Robotics & IoT Innovation Hub",
            department="ECE",
            designation="Secretary",
            is_verified=True,
            status="APPROVED",
            approved_by_id=admin_dean.id,
            approved_at=datetime.utcnow() - timedelta(days=20)
        )
        db.session.add(org_prof2)

        # Pending Organizer 3 (IT Society - Awaiting Admin Approval)
        org_user3 = User(
            name="Siddharth Jain",
            email="cloud.club@college.edu",
            phone="+91 9876509988",
            role=UserRole.ORGANIZER,
            is_active=True
        )
        org_user3.set_password("Pass@123")
        db.session.add(org_user3)
        db.session.flush()

        org_prof3 = OrganizerProfile(
            user_id=org_user3.id,
            organization_name="Cloud & DevOps Student Society",
            department="IT",
            designation="Core Member & Lead",
            is_verified=False,
            status="PENDING"
        )
        db.session.add(org_prof3)

        # ----------------------------------------------------
        # 3. CREATE STUDENTS
        # ----------------------------------------------------
        students_data = [
            ("Rahul Sharma", "student1@college.edu", "1MS21CS045", "CSE", 3, "A", "+91 9123456701"),
            ("Ananya Rao", "student2@college.edu", "1MS22EC012", "ECE", 2, "B", "+91 9123456702"),
            ("Vikram Aditya", "student3@college.edu", "1MS20IT088", "IT", 4, "A", "+91 9123456703"),
            ("Sneha Kulkarni", "student4@college.edu", "1MS23ME034", "MECH", 1, "C", "+91 9123456704"),
            ("Karthik Sundaram", "student5@college.edu", "1MS21CS099", "CSE", 3, "B", "+91 9123456705")
        ]

        student_objs = []
        for name, email, roll, dept, yr, sec, phone in students_data:
            s_user = User(
                name=name,
                email=email,
                phone=phone,
                role=UserRole.STUDENT,
                is_active=True
            )
            s_user.set_password("Pass@123")
            db.session.add(s_user)
            db.session.flush()

            s_prof = StudentProfile(
                user_id=s_user.id,
                roll_number=roll,
                department=dept,
                year=yr,
                section=sec
            )
            db.session.add(s_prof)
            student_objs.append(s_user)

        db.session.commit()
        print("Users and Profiles created.")

        # ----------------------------------------------------
        # 4. CREATE EVENTS WITH LIFECYCLES
        # ----------------------------------------------------
        now = datetime.utcnow()

        # Event 1: National Hackathon (Active, Approved, Paid)
        event1 = Event(
            title="FastFest CodeStorm 24-Hour Hackathon 2026",
            slug=Event.generate_slug("FastFest CodeStorm 24-Hour Hackathon 2026"),
            organizer_id=org_user1.id,
            event_type=EventType.HACKATHON,
            department="Computer Science & Engineering",
            faculty_coordinator="Dr. K. Ramanathan",
            faculty_coordinator_contact="admin.cse@college.edu",
            contact_info="+91 9876501234 (Priya)",
            allowed_departments="ALL",
            allowed_years="ALL",
            allowed_sections="ALL",
            eligibility_notes="Open to all engineering students with valid College ID.",
            description="""Join the biggest annual 24-hour campus hackathon! Build transformative real-world solutions across Web3, CleanTech, HealthTech, Smart Cities, and Open Innovation. 

Includes 24-hour WiFi, mentorship sessions from industry leaders, midnight snacks, food, and cash prizes worth ₹50,000!""",
            rules="""1. Teams can comprise 2 to 4 members.
2. All code repositories must be initiated during the hackathon.
3. Bring your own laptops, chargers, and hardware kits.
4. Maintain academic integrity and college campus code of conduct.""",
            venue="APJ Abdul Kalam Central Auditorium & Computing Lab 4",
            start_time=now + timedelta(days=7, hours=2),
            end_time=now + timedelta(days=8, hours=2),
            registration_deadline=now + timedelta(days=6),
            max_participants=120,
            registration_fee=250.0,
            is_free=False,
            status=EventStatus.APPROVED
        )
        db.session.add(event1)
        db.session.flush()

        # Custom fields for Event 1
        cf1_1 = CustomRegistrationField(
            event_id=event1.id,
            field_name="team_name",
            field_label="Team Name (if registering as team)",
            field_type="text",
            is_required=True,
            display_order=1
        )
        cf1_2 = CustomRegistrationField(
            event_id=event1.id,
            field_name="github_repo_or_profile",
            field_label="GitHub Profile URL",
            field_type="url",
            is_required=False,
            display_order=2
        )
        cf1_3 = CustomRegistrationField(
            event_id=event1.id,
            field_name="tshirt_size",
            field_label="T-Shirt Size",
            field_type="select",
            options_csv="S, M, L, XL, XXL",
            is_required=True,
            display_order=3
        )
        db.session.add_all([cf1_1, cf1_2, cf1_3])

        # Event 2: Python Backend Workshop (Active, Approved, Free)
        event2 = Event(
            title="Hands-On Python Web Architectures Workshop",
            slug=Event.generate_slug("Hands-On Python Web Architectures Workshop"),
            organizer_id=org_user1.id,
            event_type=EventType.WORKSHOP,
            department="Information Technology",
            faculty_coordinator="Prof. Meenakshi Sundaram",
            faculty_coordinator_contact="admin.it@college.edu",
            contact_info="+91 9876501234",
            allowed_departments="CSE,IT,ECE",
            allowed_years="2,3,4",
            allowed_sections="ALL",
            eligibility_notes="Basic familiarity with Python is recommended.",
            description="""A comprehensive hands-on workshop covering relational database design, REST API architecture, authentication, QR ticketing, and payment gateway workflows.

Every participant will build and test a live modular backend from scratch.""",
            rules="""1. Attendance for both morning and afternoon sessions is compulsory.
2. Bring laptops with Python 3.10+ pre-installed.
3. Digital participation certificates will be awarded to verified attendees.""",
            venue="Sir M. Visvesvaraya Seminar Hall, IT Block",
            start_time=now + timedelta(days=3, hours=4),
            end_time=now + timedelta(days=3, hours=10),
            registration_deadline=now + timedelta(days=2),
            max_participants=80,
            registration_fee=0.0,
            is_free=True,
            status=EventStatus.REGISTRATION_OPEN
        )
        db.session.add(event2)
        db.session.flush()

        # Custom fields for Event 2
        cf2_1 = CustomRegistrationField(
            event_id=event2.id,
            field_name="operating_system",
            field_label="Laptop Operating System",
            field_type="select",
            options_csv="Windows, macOS, Ubuntu / Linux",
            is_required=True,
            display_order=1
        )
        db.session.add(cf2_1)

        # Event 3: Robotics & Drone Symposium (Pending Approval)
        event3 = Event(
            title="NextGen Autonomous Drones & Robotics Summit",
            slug=Event.generate_slug("NextGen Autonomous Drones & Robotics Summit"),
            organizer_id=org_user2.id,
            event_type=EventType.SYMPOSIUM,
            department="Electronics & Communication",
            faculty_coordinator="Dr. H. V. Venkatesh",
            faculty_coordinator_contact="admin.ece@college.edu",
            contact_info="+91 9876505678",
            allowed_departments="ALL",
            allowed_years="ALL",
            allowed_sections="ALL",
            description="""Interactive live drone flight demos, guest lectures from aerospace experts, and hardware robotics exhibitions featuring campus student innovators.""",
            rules="""1. Photography allowed only in designated demonstration arenas.
2. Follow all safety guidelines provided by the flight crew.""",
            venue="Campus Open Grounds & ECE Quadrangle",
            start_time=now + timedelta(days=12),
            end_time=now + timedelta(days=12, hours=6),
            registration_deadline=now + timedelta(days=10),
            max_participants=150,
            registration_fee=100.0,
            is_free=False,
            status=EventStatus.PENDING_APPROVAL
        )
        db.session.add(event3)

        # Event 4: Past Completed Event with Certificates
        event4 = Event(
            title="Campus Algorithmic Coding Challenge Spring 2026",
            slug=Event.generate_slug("Campus Algorithmic Coding Challenge Spring 2026"),
            organizer_id=org_user1.id,
            event_type=EventType.TECHNICAL,
            department="Computer Science & Engineering",
            faculty_coordinator="Dr. K. Ramanathan",
            faculty_coordinator_contact="admin.cse@college.edu",
            contact_info="+91 9876501234",
            allowed_departments="ALL",
            allowed_years="ALL",
            allowed_sections="ALL",
            description="""Speed algorithmic problem solving challenge focusing on graph algorithms, dynamic programming, and data structures.""",
            rules="""Individual contest. Time limit 3 hours.""",
            venue="Turing Lab 1 & 2",
            start_time=now - timedelta(days=5, hours=4),
            end_time=now - timedelta(days=5, hours=1),
            registration_deadline=now - timedelta(days=7),
            max_participants=100,
            registration_fee=0.0,
            is_free=True,
            status=EventStatus.EVENT_COMPLETED
        )
        db.session.add(event4)
        db.session.flush()

        db.session.commit()
        print("Events seeded.")

        # ----------------------------------------------------
        # 5. CREATE REGISTRATIONS, PAYMENTS, QR & ATTENDANCE
        # ----------------------------------------------------
        # Registration 1: Student 1 registered for Event 1 (Paid Hackathon, Confirmed)
        reg1_code = EventRegistration.generate_registration_code(event1.id, student_objs[0].id)
        reg1_qr = generate_ticket_qr(reg1_code)
        reg1 = EventRegistration(
            event_id=event1.id,
            student_id=student_objs[0].id,
            registration_code=reg1_code,
            qr_code_image=reg1_qr,
            status=RegistrationStatus.CONFIRMED,
            created_at=now - timedelta(days=2)
        )
        db.session.add(reg1)
        db.session.flush()

        pay1 = Payment(
            registration_id=reg1.id,
            amount=250.0,
            currency="INR",
            razorpay_order_id=f"order_seed_{reg1.id}",
            razorpay_payment_id=f"pay_seed_{reg1.id}",
            razorpay_signature="seed_signature_valid",
            status=PaymentStatus.SUCCESS,
            payment_method="UPI_GPAY"
        )
        db.session.add(pay1)

        cr1_1 = CustomFieldResponse(registration_id=reg1.id, field_id=cf1_1.id, field_value="CyberTitans")
        cr1_2 = CustomFieldResponse(registration_id=reg1.id, field_id=cf1_2.id, field_value="https://github.com/rahul-sharma-dev")
        cr1_3 = CustomFieldResponse(registration_id=reg1.id, field_id=cf1_3.id, field_value="L")
        db.session.add_all([cr1_1, cr1_2, cr1_3])

        # Registration 2: Student 2 registered for Event 2 (Free Workshop, Confirmed)
        reg2_code = EventRegistration.generate_registration_code(event2.id, student_objs[1].id)
        reg2_qr = generate_ticket_qr(reg2_code)
        reg2 = EventRegistration(
            event_id=event2.id,
            student_id=student_objs[1].id,
            registration_code=reg2_code,
            qr_code_image=reg2_qr,
            status=RegistrationStatus.CONFIRMED,
            created_at=now - timedelta(days=1)
        )
        db.session.add(reg2)
        db.session.flush()

        cr2_1 = CustomFieldResponse(registration_id=reg2.id, field_id=cf2_1.id, field_value="macOS")
        db.session.add(cr2_1)

        # Registration 3: Student 1 registered for Event 4 (Completed Coding Contest, Attended + Certificate)
        reg3_code = EventRegistration.generate_registration_code(event4.id, student_objs[0].id)
        reg3_qr = generate_ticket_qr(reg3_code)
        reg3 = EventRegistration(
            event_id=event4.id,
            student_id=student_objs[0].id,
            registration_code=reg3_code,
            qr_code_image=reg3_qr,
            status=RegistrationStatus.CONFIRMED,
            created_at=now - timedelta(days=6)
        )
        db.session.add(reg3)
        db.session.flush()

        att3 = AttendanceRecord(
            registration_id=reg3.id,
            event_id=event4.id,
            student_id=student_objs[0].id,
            marked_by_id=org_user1.id,
            scanned_at=event4.start_time + timedelta(minutes=15),
            verification_method=VerificationMethod.QR_SCAN
        )
        db.session.add(att3)

        cert3_code = Certificate.generate_certificate_code(event4.id, student_objs[0].id)
        cert3_img = generate_certificate_image(
            student_name=student_objs[0].name,
            roll_number="1MS21CS045",
            department="CSE",
            event_title=event4.title,
            event_date_str=event4.start_time.strftime('%B %d, %Y'),
            certificate_code=cert3_code
        )
        cert3 = Certificate(
            registration_id=reg3.id,
            event_id=event4.id,
            student_id=student_objs[0].id,
            certificate_code=cert3_code,
            certificate_image=cert3_img,
            issued_at=event4.end_time + timedelta(hours=2)
        )
        db.session.add(cert3)

        # Registration 4: Student 3 registered for Event 4 (Attended + Certificate)
        reg4_code = EventRegistration.generate_registration_code(event4.id, student_objs[2].id)
        reg4_qr = generate_ticket_qr(reg4_code)
        reg4 = EventRegistration(
            event_id=event4.id,
            student_id=student_objs[2].id,
            registration_code=reg4_code,
            qr_code_image=reg4_qr,
            status=RegistrationStatus.CONFIRMED,
            created_at=now - timedelta(days=6)
        )
        db.session.add(reg4)
        db.session.flush()

        att4 = AttendanceRecord(
            registration_id=reg4.id,
            event_id=event4.id,
            student_id=student_objs[2].id,
            marked_by_id=org_user1.id,
            scanned_at=event4.start_time + timedelta(minutes=20),
            verification_method=VerificationMethod.QR_SCAN
        )
        db.session.add(att4)

        cert4_code = Certificate.generate_certificate_code(event4.id, student_objs[2].id)
        cert4_img = generate_certificate_image(
            student_name=student_objs[2].name,
            roll_number="1MS20IT088",
            department="IT",
            event_title=event4.title,
            event_date_str=event4.start_time.strftime('%B %d, %Y'),
            certificate_code=cert4_code
        )
        cert4 = Certificate(
            registration_id=reg4.id,
            event_id=event4.id,
            student_id=student_objs[2].id,
            certificate_code=cert4_code,
            certificate_image=cert4_img,
            issued_at=event4.end_time + timedelta(hours=2)
        )
        db.session.add(cert4)

        # ----------------------------------------------------
        # 6. CREATE ANNOUNCEMENTS
        # ----------------------------------------------------
        ann1 = Announcement(
            event_id=event1.id,
            author_id=org_user1.id,
            title="Important: Problem Statements Released for CodeStorm Hackathon!",
            message="Check out the 5 challenge tracks on our GitHub portal. Mentors will be available on Discord starting 9:00 AM.",
            is_pinned=True,
            created_at=now - timedelta(hours=12)
        )
        ann2 = Announcement(
            event_id=event1.id,
            author_id=org_user1.id,
            title="Bring Valid College ID Card to Venue Gate 2",
            message="Entry begins at 8:30 AM at APJ Abdul Kalam Auditorium. Keep your QR ticket ready for scanning.",
            is_pinned=False,
            created_at=now - timedelta(hours=4)
        )
        ann3 = Announcement(
            event_id=event2.id,
            author_id=org_user1.id,
            title="Workshop Prerequisites & Environment Setup Guide",
            message="Please ensure Python 3.10+ and VS Code are installed on your machines prior to the morning session.",
            is_pinned=True,
            created_at=now - timedelta(hours=6)
        )
        db.session.add_all([ann1, ann2, ann3])

        db.session.commit()
        print("Database successfully seeded with realistic sample data!")
        print("\nDEMO CREDENTIALS:")
        print("--------------------------------------------------------------------------------")
        print("Student 1:                 student1@college.edu     / Pass@123")
        print("Student 2:                 student2@college.edu     / Pass@123")
        print("Approved Organizer (CSE):  organizer@college.edu    / Pass@123")
        print("Pending Organizer (IT):    cloud.club@college.edu   / Pass@123 (Awaiting Approval)")
        print("Central Dean / Admin:      admin@college.edu        / Pass@123")
        print("CSE Faculty Admin:         admin.cse@college.edu    / Pass@123")
        print("ECE Faculty Admin:         admin.ece@college.edu    / Pass@123")
        print("IT Faculty Admin:          admin.it@college.edu     / Pass@123")
        print("MECH Faculty Admin:        admin.mech@college.edu   / Pass@123")
        print("--------------------------------------------------------------------------------")

if __name__ == '__main__':
    seed_database()
