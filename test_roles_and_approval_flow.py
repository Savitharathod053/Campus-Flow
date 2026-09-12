"""
test_roles_and_approval_flow.py
End-to-end verification of the 5 canonical roles, Organizer Request lifecycle,
and Event Creation Dual-Approval System (HOD -> Dean).
"""
from datetime import datetime, timedelta
from app import create_app
from models import (
    db, User, UserRole, CollegeDepartment, StudentProfile, OrganizerProfile, FacultyProfile,
    Event, EventStatus, OrganizerRequest, OrganizerRequestStatus, EventRequest, EventRequestStatus,
    Notification, NotificationType
)

def run_test():
    app = create_app()
    with app.app_context():
        client = app.test_client()
        print("=" * 70)
        print("CAMPUS FLOW — ROLE & DUAL APPROVAL SYSTEM VERIFICATION TEST")
        print("=" * 70)

        # 1. VERIFY EXACT 5 CANONICAL ROLES IN DB
        print("\n--- TEST 1: Canonical Roles Check ---")
        canonical_roles = set(UserRole.CHOICES)
        expected_roles = {'super_admin', 'students_affairs_dean', 'hod', 'organizer', 'student'}
        assert canonical_roles == expected_roles, f"Roles mismatch: {canonical_roles} vs {expected_roles}"
        print(f"PASS: Exact 5 roles verified: {canonical_roles}")

        # Check existing users roles in DB
        users = User.query.all()
        user_roles_in_db = {u.role for u in users}
        assert user_roles_in_db.issubset(expected_roles), f"Found non-canonical roles in DB: {user_roles_in_db}"
        print(f"PASS: All {len(users)} users in DB have canonical roles: {user_roles_in_db}")

        # Ensure we have departments
        cse_dept = CollegeDepartment.query.filter_by(code='CSE').first()
        ece_dept = CollegeDepartment.query.filter_by(code='ECE').first()
        assert cse_dept is not None, "CSE department missing"
        assert ece_dept is not None, "ECE department missing"

        # Find or create test actors
        # Super Admin
        super_admin = User.query.filter_by(role=UserRole.SUPER_ADMIN).first()
        assert super_admin is not None, "Super admin missing"

        # Students Affairs Dean
        dean = User.query.filter_by(role=UserRole.STUDENTS_AFFAIRS_DEAN).first()
        assert dean is not None, "Students Affairs Dean missing"

        # CSE HOD
        cse_hod = cse_dept.hod
        if not cse_hod:
            cse_hod = User.query.filter_by(role=UserRole.HOD).first()
            cse_dept.hod_id = cse_hod.id
            db.session.commit()
        assert cse_hod is not None, "CSE HOD missing"

        # ECE HOD
        ece_hod = ece_dept.hod
        if not ece_hod:
            ece_hod = User.query.filter(User.role == UserRole.HOD, User.id != cse_hod.id).first()
            if not ece_hod:
                # Create ECE HOD for testing cross-dept check
                ece_hod = User(email="ece.hod@college.edu", name="Dr. ECE HOD", role=UserRole.HOD)
                ece_hod.set_password("Hod@12345")
                db.session.add(ece_hod)
                db.session.flush()
            ece_dept.hod_id = ece_hod.id
            db.session.commit()

        # Test Student (in CSE)
        test_student = User.query.filter_by(email="test.student.approval@college.edu").first()
        if not test_student:
            test_student = User(
                email="test.student.approval@college.edu",
                name="Aakash Sharma",
                role=UserRole.STUDENT,
                phone="9876500001"
            )
            test_student.set_password("Student@12345")
            db.session.add(test_student)
            db.session.flush()
            profile = StudentProfile(
                user_id=test_student.id,
                roll_number="CSE-2026-999",
                department="CSE",
                year=3,
                section="A"
            )
            db.session.add(profile)
            db.session.commit()
        else:
            test_student.role = UserRole.STUDENT
            db.session.commit()

        print(f"Super Admin: {super_admin.email} (Role: {super_admin.role})")
        print(f"Dean: {dean.email} (Role: {dean.role})")
        print(f"CSE HOD: {cse_hod.email} (Role: {cse_hod.role})")
        print(f"ECE HOD: {ece_hod.email} (Role: {ece_hod.role})")
        print(f"Test Student: {test_student.email} (Role: {test_student.role})")

        # 2. TEST ORGANIZER REQUEST FLOW (Student -> CSE HOD -> Promotion)
        print("\n--- TEST 2: Organizer Request Flow ---")
        # Clean prior test requests for this student
        OrganizerRequest.query.filter_by(student_id=test_student.id).delete()
        db.session.commit()

        # Student submits organizer request
        with client.session_transaction() as sess:
            sess['user_id'] = test_student.id

        resp = client.post('/student/organizer-request', data={
            'organization_name': 'CSE Coding Society',
            'reason': 'We want to conduct a 24-hour Python Hackathon for CSE undergraduates.'
        }, follow_redirects=True)
        assert resp.status_code == 200, f"Organizer request submit failed with {resp.status_code}"

        # Verify OrganizerRequest record created with correct department routing
        org_req = OrganizerRequest.query.filter_by(student_id=test_student.id).first()
        assert org_req is not None, "OrganizerRequest was not created"
        assert org_req.department_id == cse_dept.id, f"Wrong department: {org_req.department_id} vs {cse_dept.id}"
        assert org_req.status == OrganizerRequestStatus.PENDING, f"Wrong status: {org_req.status}"
        print(f"PASS: OrganizerRequest #{org_req.id} created and routed to CSE HOD (Dept ID: {cse_dept.id})")

        # Verify in-app notification sent to CSE HOD
        hod_notif = Notification.query.filter_by(
            user_id=cse_hod.id,
            type=NotificationType.ORGANIZER_REQUEST
        ).order_by(Notification.created_at.desc()).first()
        assert hod_notif is not None, "Notification to HOD not created"
        print(f"PASS: In-app notification received by CSE HOD: '{hod_notif.title}'")

        # Security check: ECE HOD cannot approve CSE student's organizer request
        with client.session_transaction() as sess:
            sess['user_id'] = ece_hod.id
        resp = client.post(f'/hod/organizer-requests/{org_req.id}/approve', follow_redirects=True)
        assert org_req.status == OrganizerRequestStatus.PENDING, "Cross-department approval was not blocked!"
        print("PASS: Cross-department organizer approval correctly blocked by HOD access guard.")

        # CSE HOD approves the request
        with client.session_transaction() as sess:
            sess['user_id'] = cse_hod.id
        resp = client.post(f'/hod/organizer-requests/{org_req.id}/approve', follow_redirects=True)
        assert resp.status_code == 200

        db.session.refresh(org_req)
        db.session.refresh(test_student)
        assert org_req.status == OrganizerRequestStatus.APPROVED, f"Status not approved: {org_req.status}"
        assert org_req.reviewed_by_hod_id == cse_hod.id
        assert test_student.role == UserRole.ORGANIZER, f"Student role not promoted to organizer: {test_student.role}"
        assert test_student.is_organizer == True
        print(f"PASS: CSE HOD approved request. User role promoted to: {test_student.role}")

        # Verify Student received approval notification
        student_notif = Notification.query.filter_by(
            user_id=test_student.id,
            type=NotificationType.ORGANIZER_APPROVAL
        ).order_by(Notification.created_at.desc()).first()
        assert student_notif is not None, "Notification to student not created"
        print(f"PASS: In-app notification received by student: '{student_notif.title}'")

        # 3. TEST DUAL APPROVAL EVENT WORKFLOW
        # Step 1: Organizer submits proposal -> pending_hod_approval
        # Step 2: HOD endorses -> pending_dean_approval
        # Step 3: Dean approves -> approved & is_published = True
        print("\n--- TEST 3: Event Creation Dual Approval Workflow ---")
        start_time = datetime.utcnow() + timedelta(days=5)
        end_time = start_time + timedelta(hours=6)
        deadline = start_time - timedelta(days=1)

        # Login as newly promoted organizer
        with client.session_transaction() as sess:
            sess['user_id'] = test_student.id

        event_title = f"AI Cloud Summit 2026 {int(datetime.utcnow().timestamp())}"
        resp = client.post('/organizer/events/create', data={
            'title': event_title,
            'event_type': 'WORKSHOP',
            'department': 'CSE',
            'venue': 'APJ Kalam Auditorium',
            'start_time': start_time.strftime('%Y-%m-%dT%H:%M'),
            'end_time': end_time.strftime('%Y-%m-%dT%H:%M'),
            'registration_deadline': deadline.strftime('%Y-%m-%dT%H:%M'),
            'max_participants': '150',
            'is_free': 'on',
            'faculty_coordinator': 'Dr. Ramanathan',
            'faculty_coordinator_contact': 'ramanathan@college.edu',
            'description': 'Comprehensive hands-on workshop on generative AI and deployment.'
        }, follow_redirects=True)
        assert resp.status_code == 200

        # Verify EventRequest created
        ev_req = EventRequest.query.filter_by(event_name=event_title).first()
        assert ev_req is not None, "EventRequest record was not created"
        assert ev_req.overall_status == EventRequestStatus.PENDING_HOD_APPROVAL, f"Status: {ev_req.overall_status}"
        assert ev_req.department_id == cse_dept.id
        print(f"PASS: EventRequest #{ev_req.id} created with status 'pending_hod_approval'")

        # CRITICAL TEST: Event MUST NOT be published or visible in student catalog
        other_student = User.query.filter_by(role=UserRole.STUDENT).first()
        with client.session_transaction() as sess:
            sess['user_id'] = other_student.id if other_student else None
        resp = client.get('/events')
        assert event_title not in resp.get_data(as_text=True), "UNAPPROVED EVENT LEAKED TO STUDENT EVENTS CATALOG!"
        print("PASS: Event is strictly invisible to students / public before dual approval.")

        # Security check: Dean CANNOT approve before HOD approves
        with client.session_transaction() as sess:
            sess['user_id'] = dean.id
        resp = client.post(f'/dean/requests/{ev_req.id}/approve', follow_redirects=True)
        db.session.refresh(ev_req)
        assert ev_req.overall_status == EventRequestStatus.PENDING_HOD_APPROVAL, "Dean was able to approve before HOD!"
        print("PASS: Dean cannot approve proposal without prior HOD endorsement.")

        # Security check: ECE HOD cannot endorse CSE proposal
        with client.session_transaction() as sess:
            sess['user_id'] = ece_hod.id
        resp = client.post(f'/hod/event-requests/{ev_req.id}/approve', follow_redirects=True)
        db.session.refresh(ev_req)
        assert ev_req.overall_status == EventRequestStatus.PENDING_HOD_APPROVAL, "Cross-department HOD endorsement allowed!"
        print("PASS: Cross-department event endorsement correctly blocked.")

        # STEP 1 DUAL APPROVAL: CSE HOD Endorses
        with client.session_transaction() as sess:
            sess['user_id'] = cse_hod.id
        resp = client.post(f'/hod/event-requests/{ev_req.id}/approve', follow_redirects=True)
        assert resp.status_code == 200

        db.session.refresh(ev_req)
        assert ev_req.overall_status == EventRequestStatus.PENDING_DEAN_APPROVAL, f"Status: {ev_req.overall_status}"
        assert ev_req.hod_approval_status == 'approved'
        assert ev_req.hod_reviewer_id == cse_hod.id
        print(f"PASS: Step 1 complete. HOD endorsed. Status forwarded to 'pending_dean_approval'")

        # CRITICAL TEST: Even after HOD approval, event MUST STILL NOT be published!
        ev_published_check = Event.query.filter_by(title=event_title, is_published=True).first()
        assert ev_published_check is None, "Event was published prematurely in DB!"

        other_student = User.query.filter_by(role=UserRole.STUDENT).first()
        with client.session_transaction() as sess:
            sess['user_id'] = other_student.id if other_student else None
        resp = client.get('/events')
        assert event_title not in resp.get_data(as_text=True), "EVENT PUBLISHED PREMATURELY WITHOUT DEAN APPROVAL!"
        print("PASS: Event remains unpublished after Step 1 (HOD approval alone is insufficient).")

        # STEP 2 DUAL APPROVAL: Students Affairs Dean Approves
        with client.session_transaction() as sess:
            sess['user_id'] = dean.id
        resp = client.post(f'/dean/requests/{ev_req.id}/approve', follow_redirects=True)
        assert resp.status_code == 200

        db.session.refresh(ev_req)
        assert ev_req.overall_status == EventRequestStatus.APPROVED, f"Status: {ev_req.overall_status}"
        assert ev_req.dean_approval_status == 'approved'
        assert ev_req.dean_reviewer_id == dean.id
        assert ev_req.event_id is not None, "Event was not created / linked"

        # Verify Event record flags
        published_event = Event.query.get(ev_req.event_id)
        assert published_event is not None
        assert published_event.is_published == True, "Event.is_published is not True"
        assert published_event.hod_approved == True, "Event.hod_approved is not True"
        assert published_event.dean_approved == True, "Event.dean_approved is not True"
        assert published_event.status == EventStatus.APPROVED
        print(f"PASS: Step 2 complete. Dean approved. Event #{published_event.id} is officially published!")

        # Verify event IS NOW visible in student catalog
        with client.session_transaction() as sess:
            sess['user_id'] = test_student.id
        resp = client.get('/events')
        assert event_title in resp.get_data(as_text=True), "Published event not appearing in catalog!"
        print(f"PASS: Published event '{event_title}' is now discoverable by students!")

        # 4. TEST EVENT REJECTION FLOW (HOD and Dean rejection paths)
        print("\n--- TEST 4: Event Rejection Flows ---")
        # Test 4A: Rejected by HOD
        ev_req2 = EventRequest(
            organizer_id=test_student.id,
            department_id=cse_dept.id,
            event_name="Rejected By HOD Event",
            description="Workshop on technical topics.",
            proposed_event_date=start_time.date(),
            category="WORKSHOP",
            venue="Room 101",
            start_time=start_time,
            end_time=end_time,
            overall_status=EventRequestStatus.PENDING_HOD_APPROVAL
        )
        db.session.add(ev_req2)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['user_id'] = cse_hod.id
        resp = client.post(f'/hod/event-requests/{ev_req2.id}/reject', data={
            'reason': 'Venue conflict with semester examinations.'
        }, follow_redirects=True)
        db.session.refresh(ev_req2)
        assert ev_req2.overall_status == EventRequestStatus.REJECTED_BY_HOD
        assert ev_req2.hod_rejection_reason == 'Venue conflict with semester examinations.'
        print(f"PASS: HOD rejection stopped workflow and logged reason.")

        # Test 4B: Rejected by Dean after HOD endorsement
        ev_req3 = EventRequest(
            organizer_id=test_student.id,
            department_id=cse_dept.id,
            event_name="Rejected By Dean Event",
            description="Seminar on college leadership.",
            proposed_event_date=start_time.date(),
            category="SEMINAR",
            venue="Auditorium",
            start_time=start_time,
            end_time=end_time,
            hod_approval_status='approved',
            hod_reviewer_id=cse_hod.id,
            overall_status=EventRequestStatus.PENDING_DEAN_APPROVAL
        )
        db.session.add(ev_req3)
        db.session.commit()

        with client.session_transaction() as sess:
            sess['user_id'] = dean.id
        resp = client.post(f'/dean/requests/{ev_req3.id}/reject', data={
            'reason': 'Overlaps with college annual day celebrations.'
        }, follow_redirects=True)
        db.session.refresh(ev_req3)
        assert ev_req3.overall_status == EventRequestStatus.REJECTED_BY_DEAN
        assert ev_req3.dean_rejection_reason == 'Overlaps with college annual day celebrations.'
        print(f"PASS: Dean rejection stopped workflow and logged reason.")

        # 5. VERIFY ALL 5 DASHBOARDS LOAD WITH 200 OK
        print("\n--- TEST 5: All 5 Role Dashboards Access Check ---")
        student_user = User.query.filter_by(role=UserRole.STUDENT).first()
        assert student_user is not None, "A student user is required for student dashboard verification"

        role_dashboards = [
            (super_admin.id, '/admin/dashboard', 'Super Admin Dashboard'),
            (dean.id, '/dean/dashboard', 'Students Affairs Dean Portal'),
            (cse_hod.id, '/hod/dashboard', 'HOD Dashboard'),
            (test_student.id, '/organizer/dashboard', 'Organizer Dashboard'),
            (student_user.id, '/student/dashboard', 'Student Dashboard')
        ]

        for user_id, path, label in role_dashboards:
            with client.session_transaction() as sess:
                sess['user_id'] = user_id
            resp = client.get(path)
            assert resp.status_code == 200, f"{label} ({path}) returned {resp.status_code}"
            print(f"PASS: {label} [{path}] loaded successfully (HTTP 200)")

        # Verify Super Admin overview routes
        with client.session_transaction() as sess:
            sess['user_id'] = super_admin.id
        resp1 = client.get('/admin/event-requests')
        assert resp1.status_code == 200, f"/admin/event-requests returned {resp1.status_code}"
        resp2 = client.get('/admin/organizer-requests')
        assert resp2.status_code == 200, f"/admin/organizer-requests returned {resp2.status_code}"
        print(f"PASS: Super Admin event requests and organizer requests views loaded (HTTP 200)")

        print("\n" + "=" * 70)
        print("ALL TESTS PASSED SUCCESSFULLY! FULL ROLE & APPROVAL SYSTEM VERIFIED.")
        print("=" * 70)

if __name__ == '__main__':
    run_test()
