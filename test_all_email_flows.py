"""
Campus Flow - Complete Notification & Email Workflow Validation Script
Executes and validates every email and notification flow in the system.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta

from app import create_app
from models import (
    db, User, UserRole, StudentProfile, OrganizerProfile,
    Event, EventStatus, EventType, EventRegistration, RegistrationStatus,
    Payment, PaymentStatus, AttendanceSession, AttendanceRecord, AttendanceStatus,
    Certificate, CertificateStatus, CollegeDepartment,
    OrganizerRequest, OrganizerRequestStatus, EventRequest, EventRequestStatus,
    Team, TeamRole, TeamMember, TeamMemberStatus, TeamInvitation, InvitationStatus
)
from services.email_service import get_sent_emails, clear_sent_emails

def run_tests():
    app = create_app()
    with app.app_context():
        # Set testing mode so emails are logged in SENT_EMAILS without needing a live network round-trip for each unit test
        app.config['TESTING'] = True
        clear_sent_emails()

        print("=" * 80)
        print(" CAMPUS FLOW - NOTIFICATION & EMAIL FLOW TEST SUITE")
        print("=" * 80)

        results = {}

        # ----------------------------------------------------------------------
        # Flow 1: Student Account Registration
        # ----------------------------------------------------------------------
        print("\n[Flow 1] Student Registration Welcome Email...")
        test_student = User.query.filter(User.email.like('%student%')).first() or User.query.filter_by(role=UserRole.STUDENT).first()
        if not test_student:
            test_student = User(name="Test Student", email="student.test@college.edu", role=UserRole.STUDENT)
            test_student.set_password("Pass123!")
            db.session.add(test_student)
            db.session.commit()

        from services.email_service import send_account_registration_email
        send_account_registration_email(test_student)
        last_email = get_sent_emails()[-1]
        assert last_email['to'] == test_student.email
        assert "Welcome to Campus Flow" in last_email['subject']
        results['Student Registration Welcome'] = f"Delivered to {last_email['to']}"
        print(f" -> OK: Sent to {last_email['to']} | Subject: {last_email['subject']}")

        # ----------------------------------------------------------------------
        # Flow 2: Organizer Registration Submitted (Applicant + HOD Notice)
        # ----------------------------------------------------------------------
        print("\n[Flow 2] Organizer Registration Submitted (Applicant + Faculty/HOD Notice)...")
        hod_user = User.query.filter_by(role=UserRole.HOD).first()
        if not hod_user:
            hod_user = User(name="Dr. HOD Test", email="hod.test@college.edu", role=UserRole.HOD)
            hod_user.set_password("Pass123!")
            db.session.add(hod_user)
            db.session.commit()

        test_org_applicant = User.query.filter_by(email="org.applicant@college.edu").first()
        if not test_org_applicant:
            test_org_applicant = User(name="Org Applicant", email="org.applicant@college.edu", role=UserRole.ORGANIZER)
            test_org_applicant.set_password("Pass123!")
            db.session.add(test_org_applicant)
            db.session.commit()

        from services.email_service import (
            send_organizer_application_received_email,
            send_organizer_registration_faculty_notice_email
        )
        send_organizer_application_received_email(test_org_applicant, assigned_admin_name=hod_user.name)
        send_organizer_registration_faculty_notice_email(test_org_applicant, hod_user, "Computer Science")

        emails = get_sent_emails()
        applicant_email = emails[-2]
        hod_email = emails[-1]
        assert applicant_email['to'] == test_org_applicant.email
        assert hod_email['to'] == hod_user.email
        results['Organizer Registration (Applicant)'] = f"Delivered to {applicant_email['to']}"
        results['Organizer Registration (HOD Notice)'] = f"Delivered to {hod_email['to']}"
        print(f" -> OK: Applicant: {applicant_email['to']} | Subject: {applicant_email['subject']}")
        print(f" -> OK: Faculty/HOD: {hod_email['to']} | Subject: {hod_email['subject']}")

        # ----------------------------------------------------------------------
        # Flow 3: Organizer Request Approved & Rejected by HOD
        # ----------------------------------------------------------------------
        print("\n[Flow 3] Organizer Approved / Rejected by HOD...")
        dept = CollegeDepartment.query.first()
        if not dept:
            dept = CollegeDepartment(name="Computer Science & Engineering", code="CSE")
            db.session.add(dept)
            db.session.commit()

        org_req = OrganizerRequest.query.first()
        if not org_req:
            org_req = OrganizerRequest(
                student_id=test_student.id,
                department_id=dept.id,
                reason="Passionate about campus hackathons",
                status=OrganizerRequestStatus.PENDING
            )
            db.session.add(org_req)
            db.session.commit()

        from services.email_service import (
            send_organizer_request_approved_email,
            send_organizer_request_rejected_email
        )
        send_organizer_request_approved_email(org_req, test_student, hod_user)
        app_email = get_sent_emails()[-1]
        assert app_email['to'] == test_student.email
        assert "Approved" in app_email['subject']
        results['Organizer Approved by HOD'] = f"Delivered to {app_email['to']}"
        print(f" -> OK: Approved: {app_email['to']} | Subject: {app_email['subject']}")

        send_organizer_request_rejected_email(org_req, test_student, hod_user, reason="Need more event experience")
        rej_email = get_sent_emails()[-1]
        assert rej_email['to'] == test_student.email
        assert "Need more event experience" in rej_email['body']
        results['Organizer Rejected by HOD'] = f"Delivered to {rej_email['to']}"
        print(f" -> OK: Rejected: {rej_email['to']} | Subject: {rej_email['subject']}")

        # ----------------------------------------------------------------------
        # Flow 4: Event Proposal Submitted (HOD Notice + Organizer Confirmation)
        # ----------------------------------------------------------------------
        print("\n[Flow 4] Event Proposal Submitted (HOD + Organizer Confirm)...")
        event_req = EventRequest.query.first()
        dept = CollegeDepartment.query.first()
        if not event_req:
            event_req = EventRequest(
                organizer_id=test_org_applicant.id,
                department_id=dept.id,
                event_name="Annual Tech Fest 2026",
                description="Annual College Technical Festival with coding events and workshops.",
                category="Technical",
                proposed_event_date="2026-10-15",
                start_time=datetime.utcnow() + timedelta(days=20),
                end_time=datetime.utcnow() + timedelta(days=21),
                venue="Main Auditorium",
                expected_participants=250,
                overall_status=EventRequestStatus.PENDING_HOD_APPROVAL
            )
            db.session.add(event_req)
            db.session.commit()

        from services.email_service import (
            send_event_request_submitted_email,
            send_event_request_submitted_organizer_confirm_email
        )
        send_event_request_submitted_email(event_req, test_org_applicant, hod_user, dept)
        send_event_request_submitted_organizer_confirm_email(event_req, test_org_applicant, hod_user, dept)

        emails = get_sent_emails()
        ev_hod_email = emails[-2]
        ev_org_email = emails[-1]
        assert ev_hod_email['to'] == hod_user.email
        assert ev_org_email['to'] == test_org_applicant.email
        results['Event Submitted (HOD Notice)'] = f"Delivered to {ev_hod_email['to']}"
        results['Event Submitted (Organizer Confirm)'] = f"Delivered to {ev_org_email['to']}"
        print(f" -> OK: HOD Notice: {ev_hod_email['to']} | Subject: {ev_hod_email['subject']}")
        print(f" -> OK: Organizer Confirm: {ev_org_email['to']} | Subject: {ev_org_email['subject']}")

        # ----------------------------------------------------------------------
        # Flow 5: Event Approved & Rejected by HOD
        # ----------------------------------------------------------------------
        print("\n[Flow 5] Event Approved & Rejected by HOD...")
        dean_user = User.query.filter_by(role=UserRole.STUDENTS_AFFAIRS_DEAN).first()
        if not dean_user:
            dean_user = User(name="Dean Students Affairs", email="dean.test@college.edu", role=UserRole.STUDENTS_AFFAIRS_DEAN)
            dean_user.set_password("Pass123!")
            db.session.add(dean_user)
            db.session.commit()

        from services.email_service import (
            send_event_request_hod_approved_email,
            send_event_request_hod_rejected_email
        )
        send_event_request_hod_approved_email(event_req, test_org_applicant, dean_user, hod_user)
        emails = get_sent_emails()
        dean_notif = emails[-2]
        org_notif = emails[-1]
        assert dean_notif['to'] == dean_user.email
        assert org_notif['to'] == test_org_applicant.email
        results['Event HOD Approved (Dean Notice)'] = f"Delivered to {dean_notif['to']}"
        results['Event HOD Approved (Organizer Notice)'] = f"Delivered to {org_notif['to']}"
        print(f" -> OK: Dean Forwarded: {dean_notif['to']} | Subject: {dean_notif['subject']}")
        print(f" -> OK: Organizer Endorsed: {org_notif['to']} | Subject: {org_notif['subject']}")

        send_event_request_hod_rejected_email(event_req, test_org_applicant, hod_user, reason="Dates conflict with exams")
        rej_org_email = get_sent_emails()[-1]
        assert rej_org_email['to'] == test_org_applicant.email
        assert "Dates conflict with exams" in rej_org_email['body']
        results['Event HOD Rejected'] = f"Delivered to {rej_org_email['to']}"
        print(f" -> OK: Event Rejected: {rej_org_email['to']} | Subject: {rej_org_email['subject']}")

        # ----------------------------------------------------------------------
        # Flow 6: Event Approved & Rejected by Dean
        # ----------------------------------------------------------------------
        print("\n[Flow 6] Event Approved & Rejected by Dean...")
        from services.email_service import (
            send_event_request_dean_approved_email,
            send_event_request_dean_rejected_email
        )
        send_event_request_dean_approved_email(event_req, test_org_applicant, hod_user, dean_user)
        emails = get_sent_emails()
        dean_app_org = emails[-2]
        dean_app_hod = emails[-1]
        assert dean_app_org['to'] == test_org_applicant.email
        assert dean_app_hod['to'] == hod_user.email
        results['Event Dean Approved (Organizer)'] = f"Delivered to {dean_app_org['to']}"
        results['Event Dean Approved (HOD)'] = f"Delivered to {dean_app_hod['to']}"
        print(f" -> OK: Published (Organizer): {dean_app_org['to']} | Subject: {dean_app_org['subject']}")
        print(f" -> OK: Published (HOD): {dean_app_hod['to']} | Subject: {dean_app_hod['subject']}")

        send_event_request_dean_rejected_email(event_req, test_org_applicant, hod_user, dean_user, reason="Budget exceeds campus threshold")
        emails = get_sent_emails()
        dean_rej_org = emails[-2]
        dean_rej_hod = emails[-1]
        assert dean_rej_org['to'] == test_org_applicant.email
        assert dean_rej_hod['to'] == hod_user.email
        results['Event Dean Rejected (Organizer)'] = f"Delivered to {dean_rej_org['to']}"
        results['Event Dean Rejected (HOD)'] = f"Delivered to {dean_rej_hod['to']}"
        print(f" -> OK: Rejected by Dean (Organizer): {dean_rej_org['to']} | Subject: {dean_rej_org['subject']}")
        print(f" -> OK: Rejected by Dean (HOD): {dean_rej_hod['to']} | Subject: {dean_rej_hod['subject']}")

        # ----------------------------------------------------------------------
        # Flow 7: Student Event Registration Confirmed
        # ----------------------------------------------------------------------
        print("\n[Flow 7] Student Event Registration Confirmed...")
        event = Event.query.filter_by(is_published=True).first()
        if not event:
            event = Event(
                title="Grand Coding Hackathon",
                slug="grand-coding-hackathon-2026",
                description="Annual college coding fest",
                category="Hackathon",
                venue="Lab 4",
                start_time=datetime.utcnow() + timedelta(days=10),
                end_time=datetime.utcnow() + timedelta(days=11),
                registration_deadline=datetime.utcnow() + timedelta(days=5),
                is_published=True,
                status=EventStatus.APPROVED,
                organizer_id=test_org_applicant.id
            )
            db.session.add(event)
            db.session.commit()

        registration = EventRegistration.query.filter_by(event_id=event.id, student_id=test_student.id).first()
        if not registration:
            registration = EventRegistration(
                event_id=event.id,
                student_id=test_student.id,
                registration_code="CF-TEST-REG-2026",
                status=RegistrationStatus.CONFIRMED
            )
            db.session.add(registration)
            db.session.commit()

        from services.email_service import send_registration_confirmation_email
        send_registration_confirmation_email(registration, test_student, event)
        reg_email = get_sent_emails()[-1]
        assert reg_email['to'] == test_student.email
        assert "Registration Confirmed" in reg_email['subject']
        results['Event Registration Confirmed'] = f"Delivered to {reg_email['to']}"
        print(f" -> OK: Registration Confirmed: {reg_email['to']} | Subject: {reg_email['subject']}")

        # ----------------------------------------------------------------------
        # Flow 8: Payment Submitted for Verification
        # ----------------------------------------------------------------------
        print("\n[Flow 8] Payment Proof Submitted for Verification...")
        payment = Payment.query.filter_by(registration_id=registration.id).first()
        if not payment:
            payment = Payment(
                registration_id=registration.id,
                event_id=event.id,
                student_id=test_student.id,
                organizer_id=event.organizer_id,
                amount=250.0,
                transaction_id="UPI123456789",
                status=PaymentStatus.PENDING
            )
            db.session.add(payment)
            db.session.commit()

        from services.email_service import send_payment_proof_submitted_email
        send_payment_proof_submitted_email(payment, test_student, event, test_org_applicant)
        emails = get_sent_emails()
        pay_org = emails[-2]
        pay_std = emails[-1]
        assert pay_org['to'] == test_org_applicant.email
        assert pay_std['to'] == test_student.email
        results['Payment Submitted (Organizer Notice)'] = f"Delivered to {pay_org['to']}"
        results['Payment Submitted (Student Confirm)'] = f"Delivered to {pay_std['to']}"
        print(f" -> OK: Payment to Organizer: {pay_org['to']} | Subject: {pay_org['subject']}")
        print(f" -> OK: Payment to Student: {pay_std['to']} | Subject: {pay_std['subject']}")

        # ----------------------------------------------------------------------
        # Flow 9: Payment Verified & Rejected
        # ----------------------------------------------------------------------
        print("\n[Flow 9] Payment Verified & Rejected...")
        from services.email_service import (
            send_payment_confirmation_email,
            send_payment_rejected_email
        )
        send_payment_confirmation_email(payment, test_student, event, registration)
        p_ver = get_sent_emails()[-1]
        assert p_ver['to'] == test_student.email
        assert "Payment Verified" in p_ver['subject']
        results['Payment Verified'] = f"Delivered to {p_ver['to']}"
        print(f" -> OK: Payment Verified: {p_ver['to']} | Subject: {p_ver['subject']}")

        send_payment_rejected_email(payment, test_student, event, reason="UTR could not be verified on bank records")
        p_rej = get_sent_emails()[-1]
        assert p_rej['to'] == test_student.email
        assert "UTR could not be verified on bank records" in p_rej['body']
        results['Payment Rejected'] = f"Delivered to {p_rej['to']}"
        print(f" -> OK: Payment Rejected: {p_rej['to']} | Subject: {p_rej['subject']}")

        # ----------------------------------------------------------------------
        # Flow 10: Team Invitation Sent, Accepted & Declined
        # ----------------------------------------------------------------------
        print("\n[Flow 10] Team Invitation Sent, Accepted & Declined...")
        from services.email_service import (
            send_team_invitation_email,
            send_member_response_email,
            send_member_invitation_response_member_email
        )
        team = Team.query.first()
        if not team:
            team = Team(
                team_name="Cyber Sentinels",
                event_id=event.id,
                team_lead_id=test_student.id
            )
            db.session.add(team)
            db.session.commit()

        invitation = TeamInvitation.query.filter_by(team_id=team.id, invited_email="member.invited@college.edu").first()
        if not invitation:
            invitation = TeamInvitation(
                team_id=team.id,
                event_id=event.id,
                invited_email="member.invited@college.edu",
                token=f"test-token-{uuid.uuid4().hex[:12]}",
                expires_at=datetime.utcnow() + timedelta(days=3)
            )
            db.session.add(invitation)
            db.session.commit()

        send_team_invitation_email(invitation, team, event, test_student)
        t_inv = get_sent_emails()[-1]
        assert t_inv['to'] == "member.invited@college.edu"
        results['Team Invitation Sent'] = f"Delivered to {t_inv['to']}"
        print(f" -> OK: Team Invite: {t_inv['to']} | Subject: {t_inv['subject']}")

        # Member Accepted: Lead + Member confirm
        send_member_response_email(invitation, team, event, test_student, 'ACCEPTED')
        send_member_invitation_response_member_email("member.invited@college.edu", "Invited Member", team, event, 'ACCEPTED')
        emails = get_sent_emails()
        lead_acc = emails[-2]
        mem_acc = emails[-1]
        expected_lead_email = team.lead.email if team.lead else test_student.email
        assert lead_acc['to'] == expected_lead_email
        assert mem_acc['to'] == "member.invited@college.edu"
        results['Team Accepted (Lead Notice)'] = f"Delivered to {lead_acc['to']}"
        results['Team Accepted (Member Confirm)'] = f"Delivered to {mem_acc['to']}"
        print(f" -> OK: Member Accepted (Lead): {lead_acc['to']} | Subject: {lead_acc['subject']}")
        print(f" -> OK: Member Accepted (Member): {mem_acc['to']} | Subject: {mem_acc['subject']}")

        # Member Declined: Lead + Member confirm
        send_member_response_email(invitation, team, event, test_student, 'DECLINED')
        send_member_invitation_response_member_email("member.invited@college.edu", "Invited Member", team, event, 'DECLINED')
        emails = get_sent_emails()
        lead_dec = emails[-2]
        mem_dec = emails[-1]
        assert lead_dec['to'] == expected_lead_email
        assert mem_dec['to'] == "member.invited@college.edu"
        results['Team Declined (Lead Notice)'] = f"Delivered to {lead_dec['to']}"
        results['Team Declined (Member Confirm)'] = f"Delivered to {mem_dec['to']}"
        print(f" -> OK: Member Declined (Lead): {lead_dec['to']} | Subject: {lead_dec['subject']}")
        print(f" -> OK: Member Declined (Member): {mem_dec['to']} | Subject: {mem_dec['subject']}")

        # ----------------------------------------------------------------------
        # Flow 11: Certificate Ready Notification
        # ----------------------------------------------------------------------
        print("\n[Flow 11] Certificate Ready Notification...")
        from services.email_service import send_certificate_ready_email
        cert = Certificate.query.filter_by(student_id=test_student.id, event_id=event.id).first()
        if not cert:
            cert = Certificate(
                event_id=event.id,
                student_id=test_student.id,
                certificate_code=f"CERT-{uuid.uuid4().hex[:8].upper()}",
                file_path="uploads/certificates/cert1.pdf",
                original_filename="cert1.pdf",
                status=CertificateStatus.MATCHED
            )
            db.session.add(cert)
            db.session.commit()

        send_certificate_ready_email(cert, test_student, event)
        c_email = get_sent_emails()[-1]
        assert c_email['to'] == test_student.email
        assert "Certificate Available" in c_email['subject']
        results['Certificate Ready'] = f"Delivered to {c_email['to']}"
        print(f" -> OK: Certificate Ready: {c_email['to']} | Subject: {c_email['subject']}")

        # ----------------------------------------------------------------------
        # Flow 12: Attendance Recorded Notification
        # ----------------------------------------------------------------------
        print("\n[Flow 12] Attendance Recorded Notification...")
        from services.email_service import send_attendance_marked_email
        session_obj = AttendanceSession.query.filter_by(event_id=event.id).first()
        if not session_obj:
            session_obj = AttendanceSession(
                event_id=event.id,
                session_name="Day 1 Hands-On Workshop",
                session_number=1
            )
            db.session.add(session_obj)
            db.session.commit()

        att_record = AttendanceRecord.query.filter_by(event_id=event.id, student_id=test_student.id).first()
        if not att_record:
            att_record = AttendanceRecord(
                registration_id=registration.id,
                event_id=event.id,
                student_id=test_student.id,
                session_id=session_obj.id,
                status=AttendanceStatus.PRESENT,
                scanned_at=datetime.utcnow()
            )
            db.session.add(att_record)
            db.session.commit()

        send_attendance_marked_email(test_student, event, session_obj, att_record)
        att_email = get_sent_emails()[-1]
        assert att_email['to'] == test_student.email
        assert "Attendance Confirmed" in att_email['subject']
        results['Attendance Recorded'] = f"Delivered to {att_email['to']}"
        print(f" -> OK: Attendance: {att_email['to']} | Subject: {att_email['subject']}")

        print("\n" + "=" * 80)
        print(" ALL 12 WORKFLOWS VALIDATED & PASSED SUCCESSFULLY!")
        print(f" Total Emails Generated: {len(get_sent_emails())}")
        print("=" * 80)
        return results

if __name__ == '__main__':
    run_tests()
