"""
Comprehensive Automated Test Suite for Campus Flow Team / Group Registration.
Covers all 10 scenarios requested in the specification.
"""
import os
import unittest
from datetime import datetime, timedelta
import uuid

from app import create_app
from config import Config
from models import (
    db, User, UserRole, StudentProfile, Event, EventStatus, EventType,
    EventRegistration, RegistrationStatus, Team, TeamStatus, TeamPaymentStatus,
    TeamRole, TeamMemberStatus, InvitationStatus, TeamMember, TeamInvitation,
    EventRegistrationType, TeamPaymentType, Payment, PaymentStatus
)
from services.team_service import (
    create_team, accept_invitation, decline_invitation, invite_member,
    resend_invitation, remove_or_cancel_member, process_team_payment_success,
    TeamValidationError
)
from services.email_service import get_sent_emails, clear_sent_emails

class TeamTestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or os.environ.get('DATABASE_URL') or 'sqlite:///campus_flow_test.db'


class TeamRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(TeamTestConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()
        clear_sent_emails()
        self.run_id = uuid.uuid4().hex[:6]

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def get_unique_email(self, prefix="user"):
        return f"{prefix}_{self.run_id}_{uuid.uuid4().hex[:6]}@college.edu".lower()

    def create_student(self, name=None, email=None, dept="CSE", year=3, sec="A"):
        uid = uuid.uuid4().hex[:6]
        name = name or f"Student {uid}"
        email = email or self.get_unique_email("student")
        roll = f"R-{self.run_id.upper()}-{uid.upper()}"

        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(
                name=name,
                email=email,
                phone="9876543210",
                role=UserRole.STUDENT,
                is_active=True
            )
            user.set_password("Pass@123")
            db.session.add(user)
            db.session.flush()

            profile = StudentProfile(
                user_id=user.id,
                roll_number=roll,
                department=dept,
                year=year,
                section=sec
            )
            db.session.add(profile)
            db.session.commit()
        return user

    def create_organizer(self, name="Organizer User", dept="CSE"):
        email = self.get_unique_email("organizer")
        user = User(
            name=name,
            email=email,
            role=UserRole.ORGANIZER,
            is_active=True
        )
        user.set_password("Pass@123")
        db.session.add(user)
        db.session.commit()
        return user

    def create_team_event(self, organizer, title="AI Hackathon", min_size=2, max_size=4, is_free=True, fee=0.0, reg_type=EventRegistrationType.TEAM, payment_type=TeamPaymentType.FREE, require_full=False, deadline_offset_days=5):
        uid = uuid.uuid4().hex[:6]
        now = datetime.utcnow()
        event = Event(
            title=f"{title} {self.run_id}_{uid}",
            slug=f"ai-hackathon-{self.run_id}-{uid}",
            organizer_id=organizer.id,
            event_type=EventType.HACKATHON,
            department="CSE",
            faculty_coordinator="Dr. Coordinator",
            allowed_departments="ALL",
            allowed_years="ALL",
            allowed_sections="ALL",
            registration_type=reg_type,
            min_team_size=min_size,
            max_team_size=max_size,
            team_payment_type=payment_type,
            require_full_team=require_full,
            description="24h AI Hackathon",
            venue="Main Tech Lab",
            start_time=now + timedelta(days=10),
            end_time=now + timedelta(days=11),
            registration_deadline=now + timedelta(days=deadline_offset_days),
            max_participants=100,
            registration_fee=fee,
            is_free=is_free,
            status=EventStatus.APPROVED
        )
        db.session.add(event)
        db.session.commit()
        return event

    # =========================================================================
    # SCENARIO 1 — Free Hackathon
    # Team of 4. Lead registers. 3 invitations sent. All 3 accept. All 4 get tickets.
    # =========================================================================
    def test_scenario_01_free_hackathon_full_flow(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, min_size=2, max_size=4, is_free=True, fee=0.0, payment_type=TeamPaymentType.FREE)

        lead = self.create_student("Rahul")
        priya = self.create_student("Priya")
        arjun = self.create_student("Arjun")
        sneha = self.create_student("Sneha")

        # 1. Lead creates team with 3 invited members
        team, lead_reg = create_team(
            event=event,
            lead_user=lead,
            team_name="Code Warriors",
            member_emails=[priya.email, arjun.email, sneha.email]
        )

        self.assertIsNotNone(team.id)
        self.assertEqual(team.team_name, "Code Warriors")
        self.assertEqual(team.team_lead_id, lead.id)
        self.assertEqual(team.total_confirmed_count, 1)
        self.assertTrue(lead_reg.is_confirmed)
        self.assertIsNotNone(lead_reg.qr_code_image)

        # 3 invitations should be dispatched
        self.assertEqual(len(team.invitations), 3)
        invitation_emails = [e for e in get_sent_emails() if e['type'] == 'TEAM_INVITATION']
        self.assertEqual(len(invitation_emails), 3)

        # 2. Priya accepts
        priya_inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=priya.email).first()
        t, priya_reg = accept_invitation(priya_inv.token, priya)
        self.assertEqual(priya_inv.status, InvitationStatus.ACCEPTED)
        self.assertTrue(priya_reg.is_confirmed)
        self.assertIsNotNone(priya_reg.qr_code_image)
        self.assertEqual(team.total_confirmed_count, 2)
        self.assertEqual(team.status, TeamStatus.COMPLETE)

        # 3. Arjun accepts
        arjun_inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=arjun.email).first()
        t, arjun_reg = accept_invitation(arjun_inv.token, arjun)
        self.assertTrue(arjun_reg.is_confirmed)
        self.assertEqual(team.total_confirmed_count, 3)

        # 4. Sneha accepts
        sneha_inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=sneha.email).first()
        t, sneha_reg = accept_invitation(sneha_inv.token, sneha)
        self.assertTrue(sneha_reg.is_confirmed)
        self.assertEqual(team.total_confirmed_count, 4)
        self.assertEqual(team.status, TeamStatus.FULL)

        # Verify all 4 confirmed members have distinct tickets
        all_regs = EventRegistration.query.filter_by(event_id=event.id, team_id=team.id).all()
        self.assertEqual(len(all_regs), 4)
        for r in all_regs:
            self.assertTrue(r.is_confirmed)
            self.assertIsNotNone(r.qr_code_image)
            self.assertTrue(r.registration_code.startswith("CF-E"))

    # =========================================================================
    # SCENARIO 2 — One Member Declines & Replacement Invited
    # =========================================================================
    def test_scenario_02_member_declines_and_replacement(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, min_size=2, max_size=4)

        lead = self.create_student("Rahul")
        priya = self.create_student("Priya")
        sneha = self.create_student("Sneha")
        replacement = self.create_student("Vikram")

        team, lead_reg = create_team(
            event=event,
            lead_user=lead,
            team_name="Dev Dynamos",
            member_emails=[priya.email, sneha.email]
        )

        # Priya accepts
        priya_inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=priya.email).first()
        accept_invitation(priya_inv.token, priya)

        # Sneha declines
        sneha_inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=sneha.email).first()
        decline_invitation(sneha_inv.token, sneha)
        self.assertEqual(sneha_inv.status, InvitationStatus.DECLINED)

        # Team has 2 confirmed (Rahul, Priya), Sneha declined. Team can invite replacement!
        self.assertTrue(team.can_invite_more)

        # Lead invites Vikram as replacement
        new_inv = invite_member(team, replacement.email, lead)
        self.assertEqual(new_inv.invited_email, replacement.email)

        # Vikram accepts
        t, vikram_reg = accept_invitation(new_inv.token, replacement)
        self.assertTrue(vikram_reg.is_confirmed)
        self.assertEqual(team.total_confirmed_count, 3)

    # =========================================================================
    # SCENARIO 3 — Pending Member Tracking
    # =========================================================================
    def test_scenario_03_pending_member_tracking(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, min_size=2, max_size=4)

        lead = self.create_student("Lead")
        m1 = self.create_student("M1")
        m2 = self.create_student("M2")
        m3_email = self.get_unique_email("unregistered")

        team, lead_reg = create_team(
            event=event,
            lead_user=lead,
            team_name="Trio Track",
            member_emails=[m1.email, m2.email, m3_email]
        )

        # Lead + M1 accept -> 2 confirmed, 2 pending
        m1_inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=m1.email).first()
        accept_invitation(m1_inv.token, m1)

        self.assertEqual(team.total_confirmed_count, 2)
        active_pending_invites = [i for i in team.invitations if i.is_active]
        self.assertEqual(len(active_pending_invites), 2)
        self.assertEqual(team.status, TeamStatus.COMPLETE)

    # =========================================================================
    # SCENARIO 4 — Team Size Validation (Min / Max bounds)
    # =========================================================================
    def test_scenario_04_team_size_validation(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, min_size=2, max_size=4)

        lead = self.create_student("LeadS4")

        # 1. 0 invited members (total size = 1) -> must fail since min is 2
        with self.assertRaises(TeamValidationError) as ctx:
            create_team(event, lead, "Solo Team", [])
        self.assertIn("at least 2 total members", str(ctx.exception))

        # 2. 4 invited members (total size = 5) -> must fail since max is 4
        with self.assertRaises(TeamValidationError) as ctx:
            create_team(event, lead, "Overcrowded", [
                self.get_unique_email("p1"), self.get_unique_email("p2"),
                self.get_unique_email("p3"), self.get_unique_email("p4")
            ])
        self.assertIn("exceeds maximum allowed limit of 4", str(ctx.exception))

    # =========================================================================
    # SCENARIO 5 — Duplicate Email Validation
    # =========================================================================
    def test_scenario_05_duplicate_email_rejected(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, min_size=2, max_size=4)

        lead = self.create_student("LeadS5")
        dup_email = self.get_unique_email("dup")

        # Same email entered twice
        with self.assertRaises(TeamValidationError) as ctx:
            create_team(event, lead, "Dup Team", [dup_email, dup_email])
        self.assertIn("Duplicate email found", str(ctx.exception))

        # Lead's own email entered
        with self.assertRaises(TeamValidationError) as ctx:
            create_team(event, lead, "Self Invite", [lead.email])
        self.assertIn("cannot add your own email", str(ctx.exception))

    # =========================================================================
    # SCENARIO 6 — Existing Individual Registration Cannot Join Team
    # =========================================================================
    def test_scenario_06_existing_registration_prevention(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, reg_type=EventRegistrationType.BOTH)

        student_indiv = self.create_student("Indiv Student")
        lead = self.create_student("LeadS6")

        # Register student individually first
        reg_code = EventRegistration.generate_registration_code(event.id, student_indiv.id)
        indiv_reg = EventRegistration(
            event_id=event.id,
            student_id=student_indiv.id,
            registration_code=reg_code,
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(indiv_reg)
        db.session.commit()

        # Lead tries to create team including indiv student -> fails
        with self.assertRaises(TeamValidationError) as ctx:
            create_team(event, lead, "Team Conflict", [student_indiv.email])
        self.assertIn("already registered", str(ctx.exception))

    # =========================================================================
    # SCENARIO 7 — Unauthorized Access: Non-lead cannot modify team
    # =========================================================================
    def test_scenario_07_unauthorized_team_modification(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, min_size=2, max_size=4)

        lead = self.create_student("LeadS7")
        member = self.create_student("MemberS7")
        other_user = self.create_student("Stranger")

        team, _ = create_team(event, lead, "Secure Team", [member.email])
        m_inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=member.email).first()
        accept_invitation(m_inv.token, member)

        # Stranger attempts to invite new member to lead's team -> fails
        with self.assertRaises(TeamValidationError) as ctx:
            invite_member(team, self.get_unique_email("newbie"), other_user)
        self.assertIn("Only the team lead", str(ctx.exception))

        # Member attempts to invite new member -> fails
        with self.assertRaises(TeamValidationError) as ctx:
            invite_member(team, self.get_unique_email("newbie"), member)
        self.assertIn("Only the team lead", str(ctx.exception))

        # Stranger attempts to remove lead from team -> fails
        lead_member_obj = team.members[0]
        with self.assertRaises(TeamValidationError) as ctx:
            remove_or_cancel_member(team, lead_member_obj.id, other_user)
        self.assertIn("Only the team lead", str(ctx.exception))

        # Lead attempts to remove themselves -> fails
        with self.assertRaises(TeamValidationError) as ctx:
            remove_or_cancel_member(team, lead_member_obj.id, lead)
        self.assertIn("cannot be removed", str(ctx.exception))

    # =========================================================================
    # SCENARIO 8 — Expired Invitation Cannot Be Accepted
    # =========================================================================
    def test_scenario_08_expired_invitation_rejected(self):
        organizer = self.create_organizer()
        event = self.create_team_event(organizer, min_size=2, max_size=4)

        lead = self.create_student("LeadS8")
        late_student = self.create_student("Late Student")

        team, _ = create_team(event, lead, "Time Sensitive", [late_student.email])
        inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=late_student.email).first()

        # Manually expire the invitation
        inv.expires_at = datetime.utcnow() - timedelta(days=1)
        db.session.commit()

        # Attempt to accept expired invitation
        with self.assertRaises(TeamValidationError) as ctx:
            accept_invitation(inv.token, late_student)
        self.assertIn("expired", str(ctx.exception))

    # =========================================================================
    # SCENARIO 9 — Per-Team Payment Required Workflow
    # =========================================================================
    def test_scenario_09_payment_required_flow(self):
        organizer = self.create_organizer()
        # Event with ₹800 Per-Team fee
        event = self.create_team_event(
            organizer,
            min_size=2,
            max_size=3,
            is_free=False,
            fee=800.0,
            payment_type=TeamPaymentType.PER_TEAM
        )

        lead = self.create_student("LeadS9")
        member = self.create_student("MemberS9")

        # 1. Lead creates team -> payment_status = PENDING
        team, lead_reg = create_team(event, lead, "Paid Warriors", [member.email])
        self.assertEqual(team.payment_status, TeamPaymentStatus.PENDING)
        self.assertEqual(lead_reg.status, RegistrationStatus.PENDING_PAYMENT)
        self.assertIsNone(lead_reg.qr_code_image) # No ticket until paid

        # 2. Member accepts -> registration created with PENDING_PAYMENT
        inv = TeamInvitation.query.filter_by(team_id=team.id, invited_email=member.email).first()
        t, mem_reg = accept_invitation(inv.token, member)
        self.assertEqual(mem_reg.status, RegistrationStatus.PENDING_PAYMENT)
        self.assertIsNone(mem_reg.qr_code_image)

        # 3. Lead completes payment
        process_team_payment_success(team, payment_method="SANDBOX_SIMULATED", payment_id="pay_test_123")

        self.assertEqual(team.payment_status, TeamPaymentStatus.PAID)
        self.assertEqual(lead_reg.status, RegistrationStatus.CONFIRMED)
        self.assertIsNotNone(lead_reg.qr_code_image)
        self.assertEqual(mem_reg.status, RegistrationStatus.CONFIRMED)
        self.assertIsNotNone(mem_reg.qr_code_image)

    # =========================================================================
    # SCENARIO 10 — Existing Individual Event Continues Working Normally
    # =========================================================================
    def test_scenario_10_individual_event_backward_compatibility(self):
        organizer = self.create_organizer()
        uid = uuid.uuid4().hex[:6]
        now = datetime.utcnow()

        # Individual event (normal legacy behavior)
        event = Event(
            title=f"Solo Coding Workshop {self.run_id}_{uid}",
            slug=f"solo-coding-{self.run_id}-{uid}",
            organizer_id=organizer.id,
            event_type=EventType.WORKSHOP,
            department="CSE",
            faculty_coordinator="Prof. Legacy",
            allowed_departments="ALL",
            allowed_years="ALL",
            allowed_sections="ALL",
            registration_type=EventRegistrationType.INDIVIDUAL,
            description="Individual only workshop",
            venue="Seminar Hall 1",
            start_time=now + timedelta(days=5),
            end_time=now + timedelta(days=5, hours=3),
            registration_deadline=now + timedelta(days=3),
            max_participants=50,
            is_free=True,
            status=EventStatus.APPROVED
        )
        db.session.add(event)
        db.session.commit()

        self.assertTrue(event.allows_individual_registration)
        self.assertFalse(event.allows_team_registration)

        student = self.create_student("Solo Student")

        # Student registers individually
        reg_code = EventRegistration.generate_registration_code(event.id, student.id)
        reg = EventRegistration(
            event_id=event.id,
            student_id=student.id,
            registration_code=reg_code,
            status=RegistrationStatus.CONFIRMED
        )
        db.session.add(reg)
        db.session.commit()

        self.assertTrue(reg.is_confirmed)
        self.assertIsNone(reg.team_id)
        self.assertEqual(event.confirmed_registrations_count, 1)

        # Attempt to create team on individual-only event -> must fail
        with self.assertRaises(TeamValidationError) as ctx:
            create_team(event, student, "Illegal Team", [self.get_unique_email("other")])
        self.assertIn("does not support team registration", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
