"""
Campus Flow - Team & Group Registration Service
Encapsulates all business logic, validation, and lifecycle management for teams, invitations, and member registration.
"""
from datetime import datetime, timedelta
from flask import current_app
from models import (
    db, Event, EventStatus, EventRegistration, RegistrationStatus,
    CustomFieldResponse, Payment, PaymentStatus, User,
    Team, TeamStatus, TeamPaymentStatus, TeamRole, TeamMemberStatus,
    InvitationStatus, TeamMember, TeamInvitation, EventRegistrationType, TeamPaymentType
)
from services.qr_service import generate_ticket_qr
from services.email_service import (
    send_team_invitation_email,
    send_member_response_email,
    send_registration_confirmation_email,
    send_member_invitation_response_member_email
)
from services.notification_service import create_notification
from models.notification import NotificationType


class TeamValidationError(Exception):
    """Custom exception raised when team validation fails."""
    pass


def validate_team_creation(event, lead_user, team_name, member_emails):
    """
    Validates all business constraints before creating a team.
    Returns sanitized data: (clean_team_name, clean_emails_list)
    """
    # 1. Event Status and Registration Type
    if not event.allows_team_registration:
        raise TeamValidationError(f"Event '{event.title}' does not support team registration.")

    if not event.is_live_registration_open:
        raise TeamValidationError("Registration for this event is currently closed or full.")

    # 2. Lead Eligibility
    is_eligible, reason = event.check_student_eligibility(lead_user.student_profile)
    if not is_eligible:
        raise TeamValidationError(f"Team lead eligibility check failed: {reason}")

    # 3. Check if lead is already registered for this event (individually or in a team)
    existing_reg = EventRegistration.query.filter_by(event_id=event.id, student_id=lead_user.id).first()
    if existing_reg:
        raise TeamValidationError("You are already registered for this event.")

    # Also check if lead is in an active team for this event
    existing_membership = TeamMember.query.join(Team).filter(
        Team.event_id == event.id,
        TeamMember.student_id == lead_user.id,
        TeamMember.status.in_([TeamMemberStatus.CONFIRMED, TeamMemberStatus.PENDING])
    ).first()
    if existing_membership:
        raise TeamValidationError("You are already a member of a team for this event.")

    # 4. Team Name
    clean_team_name = team_name.strip()
    if not clean_team_name:
        raise TeamValidationError("Team name is required.")

    # 5. Member Emails Sanitization & Sizing Validation
    clean_emails = []
    seen = set()
    lead_email = lead_user.email.strip().lower()

    for email in member_emails:
        email_str = email.strip().lower()
        if not email_str:
            continue
        if email_str == lead_email:
            raise TeamValidationError("You cannot add your own email as a team member.")
        if email_str in seen:
            raise TeamValidationError(f"Duplicate email found in member list: {email_str}")
        seen.add(email_str)
        clean_emails.append(email_str)

    total_team_size = 1 + len(clean_emails)  # Team Lead + invited members

    min_size = event.min_team_size or 1
    max_size = event.max_team_size or 4

    if total_team_size > max_size:
        raise TeamValidationError(f"Team size exceeds maximum allowed limit of {max_size} members (Lead + {len(clean_emails)} invited = {total_team_size}).")

    if event.require_full_team and total_team_size < max_size:
        raise TeamValidationError(f"This event requires a full team of {max_size} members.")

    if total_team_size < min_size:
        raise TeamValidationError(f"Team must have at least {min_size} total members (Lead + {min_size - 1} invited).")

    # 6. Check if invited members already registered or in active teams
    for email in clean_emails:
        user = User.query.filter_by(email=email).first()
        if user:
            existing_user_reg = EventRegistration.query.filter_by(event_id=event.id, student_id=user.id).first()
            if existing_user_reg:
                raise TeamValidationError(f"Student with email '{email}' is already registered for this event.")
            
            existing_user_member = TeamMember.query.join(Team).filter(
                Team.event_id == event.id,
                TeamMember.student_id == user.id,
                TeamMember.status == TeamMemberStatus.CONFIRMED
            ).first()
            if existing_user_member:
                raise TeamValidationError(f"Student with email '{email}' is already a confirmed member of another team for this event.")

    return clean_team_name, clean_emails


def create_team(event, lead_user, team_name, member_emails, custom_responses_data=None):
    """
    Creates a new Team, registers the team lead, creates invitations for members, and sends emails.
    """
    clean_team_name, clean_emails = validate_team_creation(event, lead_user, team_name, member_emails)

    # Determine initial payment status
    payment_status = TeamPaymentStatus.NOT_REQUIRED
    if event.team_payment_type == TeamPaymentType.PER_TEAM and not event.is_free and event.registration_fee > 0:
        payment_status = TeamPaymentStatus.PENDING

    # 1. Create Team record
    team = Team(
        event_id=event.id,
        team_name=clean_team_name,
        team_lead_id=lead_user.id,
        status=TeamStatus.PENDING,
        payment_status=payment_status
    )
    db.session.add(team)
    db.session.flush()

    # 2. Add Team Lead as confirmed TeamMember
    lead_member = TeamMember(
        team_id=team.id,
        student_id=lead_user.id,
        role=TeamRole.TEAM_LEAD,
        status=TeamMemberStatus.CONFIRMED,
        joined_at=datetime.utcnow()
    )
    db.session.add(lead_member)

    # 3. Create EventRegistration for the Team Lead
    reg_code = EventRegistration.generate_registration_code(event.id, lead_user.id)
    
    # Registration status for lead
    is_free_reg = (
        event.is_free or 
        event.registration_fee <= 0 or 
        event.team_payment_type == TeamPaymentType.FREE or
        (event.team_payment_type == TeamPaymentType.PER_TEAM and payment_status == TeamPaymentStatus.NOT_REQUIRED)
    )
    
    lead_reg_status = RegistrationStatus.CONFIRMED if is_free_reg else RegistrationStatus.PENDING_PAYMENT
    lead_qr_image = generate_ticket_qr(reg_code) if lead_reg_status == RegistrationStatus.CONFIRMED else None

    lead_registration = EventRegistration(
        event_id=event.id,
        student_id=lead_user.id,
        registration_code=reg_code,
        qr_code_image=lead_qr_image,
        status=lead_reg_status,
        team_id=team.id
    )
    db.session.add(lead_registration)
    db.session.flush()

    # Save custom responses for lead if provided
    if custom_responses_data:
        for field_id, resp_value in custom_responses_data.items():
            if resp_value:
                response_obj = CustomFieldResponse(
                    registration_id=lead_registration.id,
                    field_id=field_id,
                    field_value=resp_value
                )
                db.session.add(response_obj)

    # 4. Create TeamInvitation for each invited email & send emails
    for email in clean_emails:
        invited_user = User.query.filter_by(email=email).first()
        student_id = invited_user.id if invited_user else None

        invitation = TeamInvitation.create_invitation(
            team_id=team.id,
            event_id=event.id,
            email=email,
            student_id=student_id,
            valid_days=3
        )
        db.session.add(invitation)
        db.session.flush()

        # If user exists, also add a PENDING TeamMember entry
        if invited_user:
            member_entry = TeamMember(
                team_id=team.id,
                student_id=invited_user.id,
                role=TeamRole.MEMBER,
                status=TeamMemberStatus.PENDING,
                joined_at=datetime.utcnow()
            )
            db.session.add(member_entry)

        # Dispatch invitation email & in-app notification (if user exists)
        try:
            if invited_user:
                create_notification(
                    user_id=invited_user.id,
                    title=f"Team Invitation: {team.team_name}",
                    message=f"{lead_user.name} invited you to join team '{team.team_name}' for '{event.title}'.",
                    notification_type=NotificationType.SYSTEM,
                    link=f"/student/team-invitations/{invitation.token}/accept"
                )
            send_team_invitation_email(invitation, team, event, lead_user)
        except Exception as exc:
            current_app.logger.warning(f"Could not dispatch team invitation: {exc}")

    # 5. Recalculate team status
    team.recalculate_status()
    db.session.commit()

    if lead_reg_status == RegistrationStatus.CONFIRMED:
        try:
            create_notification(
                user_id=lead_user.id,
                title=f"Team Registered: {team.team_name}",
                message=f"Team '{team.team_name}' for '{event.title}' has been registered. Pass #{lead_registration.registration_code} confirmed.",
                notification_type=NotificationType.SYSTEM,
                link=f"/student/ticket/{lead_registration.registration_code}"
            )
            send_registration_confirmation_email(lead_registration, lead_user, event, team)
        except Exception as exc:
            current_app.logger.warning(f"Could not dispatch lead registration email: {exc}")

    return team, lead_registration


def accept_invitation(token, user):
    """
    Processes acceptance of a team invitation by an authenticated student.
    """
    invitation = TeamInvitation.query.filter_by(token=token).first()
    if not invitation:
        raise TeamValidationError("Invalid or unknown invitation token.")

    if invitation.status == InvitationStatus.ACCEPTED:
        raise TeamValidationError("This invitation has already been accepted.")

    if invitation.status == InvitationStatus.DECLINED:
        raise TeamValidationError("This invitation was previously declined.")

    if invitation.status == InvitationStatus.CANCELLED:
        raise TeamValidationError("This invitation has been cancelled by the team lead.")

    if invitation.is_expired:
        invitation.status = InvitationStatus.EXPIRED
        db.session.commit()
        raise TeamValidationError("This invitation has expired.")

    # Verify email match
    if user.email.strip().lower() != invitation.invited_email.strip().lower():
        raise TeamValidationError(
            f"Logged-in account email ({user.email}) does not match the invited email ({invitation.invited_email})."
        )

    team = invitation.team
    if not team:
        raise TeamValidationError("Associated team could not be found.")

    event = invitation.event or team.event

    # Check if team is already full
    if team.total_confirmed_count >= event.max_team_size:
        raise TeamValidationError(f"Team '{team.team_name}' has already reached its maximum capacity of {event.max_team_size} members.")

    # Check if student is already registered for this event
    existing_reg = EventRegistration.query.filter_by(event_id=event.id, student_id=user.id).first()
    if existing_reg:
        if existing_reg.team_id == team.id and existing_reg.is_confirmed:
            return team, existing_reg
        raise TeamValidationError("You already have an existing registration for this event.")

    # Check student eligibility
    if user.student_profile:
        is_eligible, reason = event.check_student_eligibility(user.student_profile)
        if not is_eligible:
            raise TeamValidationError(f"Eligibility check failed: {reason}")

    # 1. Update Invitation
    invitation.status = InvitationStatus.ACCEPTED
    invitation.responded_at = datetime.utcnow()
    invitation.invited_student_id = user.id

    # 2. Add or Update TeamMember record
    member = TeamMember.query.filter_by(team_id=team.id, student_id=user.id).first()
    if not member:
        member = TeamMember(
            team_id=team.id,
            student_id=user.id,
            role=TeamRole.MEMBER,
            status=TeamMemberStatus.CONFIRMED,
            joined_at=datetime.utcnow()
        )
        db.session.add(member)
    else:
        member.status = TeamMemberStatus.CONFIRMED

    # 3. Determine Registration & Payment Status
    # - Free event or Team payment type is FREE -> CONFIRMED & Ticket
    # - Per-team payment and team.payment_status is PAID -> CONFIRMED & Ticket
    # - Per-person payment and event is not free -> PENDING_PAYMENT
    reg_code = EventRegistration.generate_registration_code(event.id, user.id)

    is_confirmed_now = False
    if event.is_free or event.registration_fee <= 0 or event.team_payment_type == TeamPaymentType.FREE:
        is_confirmed_now = True
    elif event.team_payment_type == TeamPaymentType.PER_TEAM:
        is_confirmed_now = (team.payment_status == TeamPaymentStatus.PAID)
    elif event.team_payment_type == TeamPaymentType.PER_PERSON:
        is_confirmed_now = False

    init_status = RegistrationStatus.CONFIRMED if is_confirmed_now else RegistrationStatus.PENDING_PAYMENT
    qr_image = generate_ticket_qr(reg_code) if is_confirmed_now else None

    registration = EventRegistration(
        event_id=event.id,
        student_id=user.id,
        registration_code=reg_code,
        qr_code_image=qr_image,
        status=init_status,
        team_id=team.id
    )
    db.session.add(registration)

    # 4. Recalculate team status
    team.recalculate_status()
    db.session.commit()

    # 5. Send notifications
    try:
        # Notify Team Lead
        send_member_response_email(invitation, team, event, user, 'ACCEPTED')
        if team.team_lead_id:
            create_notification(
                user_id=team.team_lead_id,
                title=f"Team Member Joined: {user.name}",
                message=f"{user.name} has accepted your invitation to join team '{team.team_name}'.",
                notification_type=NotificationType.SYSTEM,
                link=f"/student/teams/{team.id}"
            )
        # Notify Accepting Member
        create_notification(
            user_id=user.id,
            title=f"Joined Team: {team.team_name}",
            message=f"You have joined '{team.team_name}' for '{event.title}'.",
            notification_type=NotificationType.SYSTEM,
            link=f"/student/teams/{team.id}"
        )
        send_member_invitation_response_member_email(user.email, user.name, team, event, 'ACCEPTED')

        if is_confirmed_now:
            send_registration_confirmation_email(registration, user, event, team)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch team acceptance notifications: {exc}")

    return team, registration


def decline_invitation(token, user=None):
    """
    Processes declining of a team invitation.
    """
    invitation = TeamInvitation.query.filter_by(token=token).first()
    if not invitation:
        raise TeamValidationError("Invalid or unknown invitation token.")

    if invitation.status in (InvitationStatus.ACCEPTED, InvitationStatus.DECLINED, InvitationStatus.CANCELLED):
        raise TeamValidationError(f"This invitation has already been marked as {invitation.status}.")

    invitation.status = InvitationStatus.DECLINED
    invitation.responded_at = datetime.utcnow()

    team = invitation.team
    event = invitation.event or (team.event if team else None)

    # If member record exists, update to DECLINED
    if invitation.invited_student_id:
        member = TeamMember.query.filter_by(team_id=team.id, student_id=invitation.invited_student_id).first()
        if member:
            member.status = TeamMemberStatus.DECLINED
    elif user:
        member = TeamMember.query.filter_by(team_id=team.id, student_id=user.id).first()
        if member:
            member.status = TeamMemberStatus.DECLINED

    if team:
        team.recalculate_status()

    db.session.commit()

    if team and event:
        try:
            # Notify Team Lead
            send_member_response_email(invitation, team, event, user, 'DECLINED')
            responder_name = user.name if user else invitation.invited_email
            if team.team_lead_id:
                create_notification(
                    user_id=team.team_lead_id,
                    title="Team Invitation Declined",
                    message=f"{responder_name} declined your invitation to join team '{team.team_name}'.",
                    notification_type=NotificationType.SYSTEM,
                    link=f"/student/teams/{team.id}"
                )
            # Notify Declining Member
            send_member_invitation_response_member_email(invitation.invited_email, responder_name, team, event, 'DECLINED')
            if user:
                create_notification(
                    user_id=user.id,
                    title=f"Invitation Declined: {team.team_name}",
                    message=f"You declined the invitation to join team '{team.team_name}' for '{event.title}'.",
                    notification_type=NotificationType.SYSTEM,
                    link="/student/my-events"
                )
        except Exception as exc:
            current_app.logger.warning(f"Could not dispatch team decline notifications: {exc}")

    return invitation


def invite_member(team, email, lead_user):
    """
    Allows team lead to invite a new or replacement member if team has capacity and deadline not passed.
    """
    if team.team_lead_id != lead_user.id:
        raise TeamValidationError("Only the team lead can invite new members.")

    event = team.event
    if event.is_deadline_passed:
        raise TeamValidationError("The registration deadline for this event has passed.")

    if not team.can_invite_more:
        raise TeamValidationError(f"Team has already reached the maximum limit of {event.max_team_size} members.")

    clean_email = email.strip().lower()
    if not clean_email:
        raise TeamValidationError("Valid email address is required.")

    if clean_email == lead_user.email.strip().lower():
        raise TeamValidationError("You cannot invite yourself.")

    # Check existing confirmed members
    for m in team.members:
        if m.student and m.student.email.lower() == clean_email and m.status == TeamMemberStatus.CONFIRMED:
            raise TeamValidationError(f"Student '{clean_email}' is already a confirmed member of this team.")

    # Check active pending invitations
    for inv in team.invitations:
        if inv.invited_email.lower() == clean_email and inv.is_active:
            raise TeamValidationError(f"An active invitation for '{clean_email}' is already pending.")

    # Check if student already registered for this event
    existing_user = User.query.filter_by(email=clean_email).first()
    if existing_user:
        existing_reg = EventRegistration.query.filter_by(event_id=event.id, student_id=existing_user.id).first()
        if existing_reg:
            raise TeamValidationError(f"Student with email '{clean_email}' is already registered for this event.")

    student_id = existing_user.id if existing_user else None

    invitation = TeamInvitation.create_invitation(
        team_id=team.id,
        event_id=event.id,
        email=clean_email,
        student_id=student_id,
        valid_days=3
    )
    db.session.add(invitation)

    if existing_user:
        member_entry = TeamMember.query.filter_by(team_id=team.id, student_id=existing_user.id).first()
        if not member_entry:
            member_entry = TeamMember(
                team_id=team.id,
                student_id=existing_user.id,
                role=TeamRole.MEMBER,
                status=TeamMemberStatus.PENDING,
                joined_at=datetime.utcnow()
            )
            db.session.add(member_entry)
        else:
            member_entry.status = TeamMemberStatus.PENDING

    db.session.commit()
    try:
        if existing_user:
            create_notification(
                user_id=existing_user.id,
                title=f"Team Invitation: {team.team_name}",
                message=f"{lead_user.name} invited you to join team '{team.team_name}' for '{event.title}'.",
                notification_type=NotificationType.SYSTEM,
                link=f"/student/team-invitations/{invitation.token}/accept"
            )
        send_team_invitation_email(invitation, team, event, lead_user)
    except Exception as exc:
        current_app.logger.warning(f"Could not dispatch team invitation: {exc}")
    return invitation


def resend_invitation(team, invitation_id, lead_user):
    """
    Resends an active or expired pending invitation.
    """
    if team.team_lead_id != lead_user.id:
        raise TeamValidationError("Only the team lead can resend invitations.")

    invitation = TeamInvitation.query.filter_by(id=invitation_id, team_id=team.id).first()
    if not invitation:
        raise TeamValidationError("Invitation not found.")

    if invitation.status == InvitationStatus.ACCEPTED:
        raise TeamValidationError("This invitation has already been accepted.")

    # Renew expiry date and status
    invitation.status = InvitationStatus.PENDING
    invitation.expires_at = datetime.utcnow() + timedelta(days=3)
    invitation.token = TeamInvitation.generate_token()
    db.session.commit()

    send_team_invitation_email(invitation, team, team.event, lead_user)
    return invitation


def remove_or_cancel_member(team, member_id_or_invite_id, lead_user, is_invite=False):
    """
    Allows team lead to remove a pending/declined member or cancel an invitation.
    Team lead cannot remove themselves.
    """
    if team.team_lead_id != lead_user.id:
        raise TeamValidationError("Only the team lead can manage team members.")

    if is_invite:
        invitation = TeamInvitation.query.filter_by(id=member_id_or_invite_id, team_id=team.id).first()
        if not invitation:
            raise TeamValidationError("Invitation not found.")
        invitation.status = InvitationStatus.CANCELLED
        
        # If there's an associated pending TeamMember, remove or mark REMOVED
        if invitation.invited_student_id:
            member = TeamMember.query.filter_by(team_id=team.id, student_id=invitation.invited_student_id).first()
            if member and member.status != TeamMemberStatus.CONFIRMED:
                db.session.delete(member)
        db.session.commit()
        return True
    else:
        member = TeamMember.query.filter_by(id=member_id_or_invite_id, team_id=team.id).first()
        if not member:
            raise TeamValidationError("Member record not found.")

        if member.is_lead or member.student_id == lead_user.id:
            raise TeamValidationError("The team lead cannot be removed from the team.")

        # If member was confirmed and has registration, delete or cancel registration
        reg = EventRegistration.query.filter_by(event_id=team.event_id, student_id=member.student_id).first()
        if reg:
            db.session.delete(reg)

        db.session.delete(member)
        team.recalculate_status()
        db.session.commit()
        return True


def process_team_payment_success(team, payment_method='UPI_DIRECT', transaction_id=None, payment_id=None, **kwargs):
    """
    Handles successful full-team payment (PER_TEAM model).
    Marks team payment as PAID and generates individual tickets for all confirmed members.
    """
    transaction_id = transaction_id or payment_id
    team.payment_status = TeamPaymentStatus.PAID
    
    # Confirm registrations and generate QR passes for all confirmed members
    for member in team.confirmed_members:
        reg = EventRegistration.query.filter_by(event_id=team.event_id, student_id=member.student_id).first()
        if not reg:
            reg_code = EventRegistration.generate_registration_code(team.event_id, member.student_id)
            qr_image = generate_ticket_qr(reg_code)
            reg = EventRegistration(
                event_id=team.event_id,
                student_id=member.student_id,
                registration_code=reg_code,
                qr_code_image=qr_image,
                status=RegistrationStatus.CONFIRMED,
                team_id=team.id
            )
            db.session.add(reg)
        else:
            reg.status = RegistrationStatus.CONFIRMED
            if not reg.qr_code_image:
                reg.qr_code_image = generate_ticket_qr(reg.registration_code)

        if member.student:
            send_registration_confirmation_email(reg, member.student, team.event, team)

    db.session.commit()
    return True
