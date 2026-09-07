"""
Campus Flow - Email & Notification Service
Handles email delivery for team invitations, responses, and registration confirmations.
"""
import os
import smtplib
import logging
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from flask import current_app, url_for, has_request_context
from dotenv import load_dotenv

# Ensure environment variables from .env are loaded even outside Flask application context
load_dotenv()

logger = logging.getLogger(__name__)

# In-memory store of sent emails for automated test verification and inspection
SENT_EMAILS = []

def get_sent_emails():
    """Returns the list of sent email records."""
    return SENT_EMAILS

def clear_sent_emails():
    """Clears the in-memory sent email logs."""
    SENT_EMAILS.clear()


def get_mail_config():
    """
    Reads SMTP configuration from Flask current_app.config or environment variables.
    """
    config = {}
    if current_app:
        app_cfg = current_app.config
        config['MAIL_SERVER'] = app_cfg.get('MAIL_SERVER') or os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
        config['MAIL_PORT'] = int(app_cfg.get('MAIL_PORT') or os.environ.get('MAIL_PORT', 587))
        use_tls = app_cfg.get('MAIL_USE_TLS')
        if use_tls is None:
            use_tls = os.environ.get('MAIL_USE_TLS', 'True').lower() in ('true', '1', 't', 'yes')
        config['MAIL_USE_TLS'] = use_tls
        use_ssl = app_cfg.get('MAIL_USE_SSL')
        if use_ssl is None:
            use_ssl = os.environ.get('MAIL_USE_SSL', 'False').lower() in ('true', '1', 't', 'yes')
        config['MAIL_USE_SSL'] = use_ssl
        config['MAIL_USERNAME'] = (app_cfg.get('MAIL_USERNAME') or os.environ.get('MAIL_USERNAME', '')).strip()
        config['MAIL_PASSWORD'] = (app_cfg.get('MAIL_PASSWORD') or os.environ.get('MAIL_PASSWORD', '')).strip()
        config['MAIL_DEFAULT_SENDER'] = (
            app_cfg.get('MAIL_DEFAULT_SENDER') or 
            os.environ.get('MAIL_DEFAULT_SENDER') or 
            config['MAIL_USERNAME'] or 
            'noreply@campusflow.edu'
        ).strip()
        config['TESTING'] = app_cfg.get('TESTING', False)
    else:
        config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
        config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
        config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ('true', '1', 't', 'yes')
        config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'False').lower() in ('true', '1', 't', 'yes')
        config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME', '').strip()
        config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD', '').strip()
        config['MAIL_DEFAULT_SENDER'] = (
            os.environ.get('MAIL_DEFAULT_SENDER') or 
            config['MAIL_USERNAME'] or 
            'noreply@campusflow.edu'
        ).strip()
        config['TESTING'] = os.environ.get('TESTING', 'False').lower() in ('true', '1')

    return config


def _send_smtp_worker(to_email, subject, body_text, body_html=None, config=None):
    """
    Worker function executed to transmit email via SMTP.
    Safely catches any socket, SMTP, or SSL errors without crashing the caller.
    """
    if not config:
        config = get_mail_config()

    server_host = config.get('MAIL_SERVER', 'smtp.gmail.com')
    port = config.get('MAIL_PORT', 587)
    use_tls = config.get('MAIL_USE_TLS', True)
    use_ssl = config.get('MAIL_USE_SSL', False)
    username = config.get('MAIL_USERNAME', '')
    password = config.get('MAIL_PASSWORD', '')
    sender = config.get('MAIL_DEFAULT_SENDER') or username or 'noreply@campusflow.edu'

    if not username or not password:
        logger.warning(
            f"[EMAIL NOT SENT - MISSING CREDENTIALS] To: {to_email} | Subject: '{subject}'. "
            "Please configure MAIL_USERNAME and MAIL_PASSWORD in environment variables to enable live delivery."
        )
        return False

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = sender
        msg['To'] = to_email
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid(domain='campusflow.edu')

        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        if body_html:
            msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        if use_ssl:
            server = smtplib.SMTP_SSL(server_host, port, timeout=12)
        else:
            server = smtplib.SMTP(server_host, port, timeout=12)
            if use_tls:
                server.starttls()

        server.login(username, password)
        server.sendmail(sender, [to_email], msg.as_string())
        server.quit()

        logger.info(f"[EMAIL DELIVERED] To: {to_email} | Subject: '{subject}' via {server_host}:{port}")
        return True

    except smtplib.SMTPAuthenticationError as auth_err:
        logger.error(
            f"[EMAIL AUTHENTICATION ERROR] Could not authenticate with {server_host} for user {username}. "
            f"If using Gmail, ensure a 16-character Google App Password is used instead of your primary password: {auth_err}"
        )
        return False
    except Exception as exc:
        logger.error(f"[EMAIL DELIVERY ERROR] Failed to send email to {to_email} via {server_host}:{port}: {exc}")
        return False


def dispatch_email(to_email, subject, body_text, body_html=None, sync=False):
    """
    Dispatches email. In test mode, bypasses network I/O.
    In live mode with credentials, transmits via SMTP (using a daemon thread to keep web requests responsive).
    """
    if not to_email:
        return False

    cfg = get_mail_config()
    if cfg.get('TESTING', False):
        return True

    if not cfg.get('MAIL_USERNAME') or not cfg.get('MAIL_PASSWORD'):
        logger.info(
            f"[EMAIL SIMULATED - CREDENTIALS UNSET] To: {to_email} | Subject: '{subject}'. "
            "Configure MAIL_USERNAME and MAIL_PASSWORD in Render environment variables to send live emails."
        )
        return True

    if sync:
        return _send_smtp_worker(to_email, subject, body_text, body_html, config=cfg)
    else:
        thread = threading.Thread(
            target=_send_smtp_worker,
            args=(to_email, subject, body_text, body_html, cfg),
            daemon=True
        )
        thread.start()
        return True


def test_smtp_connection(config=None):
    """
    Diagnostic tool to verify SMTP server connectivity and authentication.
    Returns (success: bool, message: str).
    """
    if not config:
        config = get_mail_config()

    server_host = config.get('MAIL_SERVER', 'smtp.gmail.com')
    port = config.get('MAIL_PORT', 587)
    use_tls = config.get('MAIL_USE_TLS', True)
    use_ssl = config.get('MAIL_USE_SSL', False)
    username = config.get('MAIL_USERNAME', '')
    password = config.get('MAIL_PASSWORD', '')

    if not username or not password:
        return False, "MAIL_USERNAME or MAIL_PASSWORD is not set in environment variables."

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(server_host, port, timeout=10)
        else:
            server = smtplib.SMTP(server_host, port, timeout=10)
            if use_tls:
                server.starttls()

        server.login(username, password)
        server.quit()
        return True, f"Successfully connected and authenticated with {server_host}:{port} as {username}."
    except Exception as e:
        return False, f"SMTP connection failed: {e}"


def send_team_invitation_email(invitation, team, event, team_lead):
    """
    Sends an invitation email to the invited member with secure accept/decline links.
    """
    if has_request_context():
        accept_url = url_for('student.accept_invitation', token=invitation.token, _external=True)
        decline_url = url_for('student.decline_invitation', token=invitation.token, _external=True)
    else:
        accept_url = f"/student/team-invitations/{invitation.token}/accept"
        decline_url = f"/student/team-invitations/{invitation.token}/decline"

    subject = f"You're invited to join team '{team.team_name}' for '{event.title}' on Campus Flow"
    body = (
        f"Hello,\n\n"
        f"You have been invited by {team_lead.name} ({team_lead.email}) to join the team '{team.team_name}' "
        f"for the event '{event.title}' on Campus Flow.\n\n"
        f"Event: {event.title}\n"
        f"Team: {team.team_name}\n"
        f"Team Lead: {team_lead.name}\n"
        f"Venue: {event.venue}\n"
        f"Event Date: {event.start_time.strftime('%b %d, %Y %I:%M %p')}\n\n"
        f"Please click below to respond to this invitation:\n"
        f"Accept Invitation: {accept_url}\n"
        f"Decline Invitation: {decline_url}\n\n"
        f"Note: This invitation is valid for 3 days.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {
        'to': invitation.invited_email,
        'subject': subject,
        'body': body,
        'token': invitation.token,
        'accept_url': accept_url,
        'decline_url': decline_url,
        'team_id': team.id,
        'event_id': event.id,
        'type': 'TEAM_INVITATION'
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] To: {invitation.invited_email} | Subject: {subject}")
    print(f"\n[EMAIL DISPATCHED]\nTo: {invitation.invited_email}\nSubject: {subject}\nAccept Link: {accept_url}\nDecline Link: {decline_url}\n")
    dispatch_email(invitation.invited_email, subject, body)
    return True


def send_member_response_email(invitation, team, event, member_user, response_type):
    """
    Notifies the team lead when an invited student accepts or declines the invitation.
    """
    lead = team.lead
    if not lead:
        return False

    responder_name = member_user.name if member_user else invitation.invited_email
    action_text = "accepted" if response_type == 'ACCEPTED' else "declined"
    subject = f"Team Update: {responder_name} has {action_text} your invitation for '{team.team_name}'"
    
    body = (
        f"Hello {lead.name},\n\n"
        f"{responder_name} ({invitation.invited_email}) has {action_text} your invitation "
        f"to join team '{team.team_name}' for the event '{event.title}'.\n\n"
        f"Current Team Status: {team.status}\n"
        f"Confirmed Members: {team.total_confirmed_count} / {event.max_team_size}\n\n"
        f"You can view and manage your team anytime on your Campus Flow dashboard.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {
        'to': lead.email,
        'subject': subject,
        'body': body,
        'team_id': team.id,
        'event_id': event.id,
        'type': f'MEMBER_{response_type}'
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] To: {lead.email} | Subject: {subject}")
    print(f"\n[EMAIL DISPATCHED]\nTo: {lead.email}\nSubject: {subject}\n")
    dispatch_email(lead.email, subject, body)
    return True


def send_registration_confirmation_email(registration, user, event, team=None):
    """
    Sends individual registration and ticket confirmation email to the attendee.
    """
    team_info = f"Team: {team.team_name}\n" if team else ""
    subject = f"Registration Confirmed: {event.title} - Pass #{registration.registration_code}"
    body = (
        f"Hello {user.name},\n\n"
        f"Your registration for '{event.title}' is confirmed!\n\n"
        f"{team_info}"
        f"Registration / Ticket Code: {registration.registration_code}\n"
        f"Date: {event.start_time.strftime('%b %d, %Y %I:%M %p')}\n"
        f"Venue: {event.venue}\n\n"
        f"Your individual entry pass and QR code are ready in your Campus Flow dashboard.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {
        'to': user.email,
        'subject': subject,
        'body': body,
        'registration_code': registration.registration_code,
        'event_id': event.id,
        'type': 'REGISTRATION_CONFIRMATION'
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Registration confirmation to: {user.email} | Ticket: {registration.registration_code}")
    dispatch_email(user.email, subject, body)
    return True


# ==============================================================================
# ORGANIZER REQUEST NOTIFICATION EMAILS
# ==============================================================================

def send_organizer_request_submitted_email(req, student, hod, dept):
    """Event 1: Student submits organizer request -> respective Department HOD."""
    if not hod or not hod.email:
        return False
    dept_name = dept.name if dept else student.student_profile.department
    subject = f"New Organizer Request: {student.name} ({dept_name})"
    body = (
        f"Dear {hod.name},\n\n"
        f"A student from your department ({dept_name}) has submitted a request to become an Event Organizer.\n\n"
        f"Student Details:\n"
        f"Name: {student.name}\n"
        f"Roll Number: {student.student_profile.roll_number if student.student_profile else 'N/A'}\n"
        f"Email: {student.email}\n"
        f"Department: {dept_name}\n"
        f"Year: {student.student_profile.year if student.student_profile else 'N/A'}\n\n"
        f"Reason for Request:\n{req.reason}\n\n"
        f"Previous Experience:\n{req.previous_experience or 'None specified'}\n\n"
        f"Please log in to your HOD Dashboard to review and approve or reject this request.\n\n"
        f"— Campus Flow System"
    )
    email_record = {'to': hod.email, 'subject': subject, 'body': body, 'type': 'ORGANIZER_REQUEST_SUBMITTED'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] To HOD: {hod.email} | Subject: {subject}")
    dispatch_email(hod.email, subject, body)
    return True


def send_organizer_request_approved_email(req, student, hod):
    """Event 2: HOD approves organizer request -> Student."""
    if not student or not student.email:
        return False
    subject = "Congratulations! Your Organizer Request has been Approved"
    body = (
        f"Dear {student.name},\n\n"
        f"Your request to become an Event Organizer has been APPROVED by your Head of Department, {hod.name}.\n\n"
        f"You now have access to the Organizer Dashboard where you can submit event creation requests for departmental and campus review.\n\n"
        f"Welcome to the Campus Flow organizing team!\n\n"
        f"— Campus Flow System"
    )
    email_record = {'to': student.email, 'subject': subject, 'body': body, 'type': 'ORGANIZER_REQUEST_APPROVED'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] To Student: {student.email} | Subject: {subject}")
    dispatch_email(student.email, subject, body)
    return True


def send_organizer_request_rejected_email(req, student, hod, reason=None):
    """Event 3: HOD rejects organizer request -> Student."""
    if not student or not student.email:
        return False
    reason_text = f"\nReason: {reason}\n" if reason else ""
    subject = "Update on Your Organizer Request"
    body = (
        f"Dear {student.name},\n\n"
        f"Thank you for your interest in becoming an Event Organizer on Campus Flow.\n\n"
        f"After review, your Head of Department ({hod.name}) was unable to approve your organizer request at this time.{reason_text}\n"
        f"Your student account remains active and you may continue discovering and registering for events.\n\n"
        f"— Campus Flow System"
    )
    email_record = {'to': student.email, 'subject': subject, 'body': body, 'type': 'ORGANIZER_REQUEST_REJECTED'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] To Student: {student.email} | Subject: {subject}")
    dispatch_email(student.email, subject, body)
    return True


# ==============================================================================
# EVENT DUAL APPROVAL NOTIFICATION EMAILS
# ==============================================================================

def send_event_request_submitted_email(req, organizer, hod, dept):
    """Event 4: Organizer submits event request -> respective Department HOD."""
    if not hod or not hod.email:
        return False
    dept_name = dept.name if dept else req.category
    subject = f"Action Required: New Event Request '{req.event_name}' - {dept_name}"
    body = (
        f"Dear {hod.name},\n\n"
        f"Organizer {organizer.name} has submitted a new event proposal requiring your departmental endorsement:\n\n"
        f"Event Name: {req.event_name}\n"
        f"Category: {req.category}\n"
        f"Proposed Date: {req.proposed_event_date}\n"
        f"Time: {req.start_time.strftime('%I:%M %p')} - {req.end_time.strftime('%I:%M %p')}\n"
        f"Venue: {req.venue}\n"
        f"Expected Participants: {req.expected_participants}\n"
        f"Budget Requirements: {req.budget_requirements or 'None'}\n\n"
        f"Please review this request on your HOD Dashboard.\n\n"
        f"Note: Once approved by you, this request will automatically be forwarded to the Students Affairs Dean for final college-level clearance.\n\n"
        f"— Campus Flow System"
    )
    email_record = {'to': hod.email, 'subject': subject, 'body': body, 'type': 'EVENT_REQUEST_SUBMITTED'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] To HOD: {hod.email} | Subject: {subject}")
    dispatch_email(hod.email, subject, body)
    return True


def send_event_request_hod_approved_email(req, organizer, dean, hod):
    """Event 5: HOD approves event request -> Organizer and Students Affairs Dean."""
    # Notify Dean
    if dean and dean.email:
        subject_dean = f"Forwarded Event Proposal: '{req.event_name}' (HOD Approved)"
        body_dean = (
            f"Dear Dean {dean.name},\n\n"
            f"The event proposal '{req.event_name}' has been reviewed and endorsed by Department HOD {hod.name} and forwarded for your final college-level review and approval.\n\n"
            f"Event: {req.event_name}\n"
            f"Organizer: {organizer.name}\n"
            f"Department HOD: {hod.name}\n"
            f"Proposed Date: {req.proposed_event_date}\n"
            f"Venue: {req.venue}\n"
            f"Expected Participants: {req.expected_participants}\n"
            f"Budget: {req.budget_requirements or 'None'}\n\n"
            f"Please review this request on your Dean Dashboard to grant final approval and publish the event.\n\n"
            f"— Campus Flow System"
        )
        SENT_EMAILS.append({'to': dean.email, 'subject': subject_dean, 'body': body_dean, 'type': 'EVENT_REQUEST_FORWARDED_TO_DEAN'})
        logger.info(f"[EMAIL SENT] To Dean: {dean.email} | Subject: {subject_dean}")
        dispatch_email(dean.email, subject_dean, body_dean)

    # Notify Organizer
    if organizer and organizer.email:
        subject_org = f"HOD Endorsed: '{req.event_name}' - Pending Dean Approval"
        body_org = (
            f"Dear {organizer.name},\n\n"
            f"Your event proposal '{req.event_name}' has been APPROVED by your Department HOD ({hod.name})!\n\n"
            f"It has now been forwarded to the Students Affairs Dean for final college-level approval. Your event will be published immediately once the Dean approves.\n\n"
            f"— Campus Flow System"
        )
        SENT_EMAILS.append({'to': organizer.email, 'subject': subject_org, 'body': body_org, 'type': 'EVENT_HOD_APPROVED_NOTIFY_ORGANIZER'})
        logger.info(f"[EMAIL SENT] To Organizer: {organizer.email} | Subject: {subject_org}")
        dispatch_email(organizer.email, subject_org, body_org)

    return True


def send_event_request_hod_rejected_email(req, organizer, hod, reason=None):
    """Event 6: HOD rejects event request -> Organizer."""
    if not organizer or not organizer.email:
        return False
    reason_text = f"\nReason: {reason}\n" if reason else ""
    subject = f"Event Proposal Update: '{req.event_name}'"
    body = (
        f"Dear {organizer.name},\n\n"
        f"Your event proposal '{req.event_name}' was reviewed by your Department HOD ({hod.name}) and was not approved.{reason_text}\n"
        f"This event will not be published. You can review the feedback on your Organizer Dashboard.\n\n"
        f"— Campus Flow System"
    )
    email_record = {'to': organizer.email, 'subject': subject, 'body': body, 'type': 'EVENT_HOD_REJECTED'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] To Organizer: {organizer.email} | Subject: {subject}")
    dispatch_email(organizer.email, subject, body)
    return True


def send_event_request_dean_approved_email(req, organizer, hod, dean, event=None):
    """Event 7: Dean approves event -> Organizer and respective HOD."""
    # Notify Organizer
    if organizer and organizer.email:
        subject_org = f"Approved & Published: '{req.event_name}' on Campus Flow!"
        body_org = (
            f"Dear {organizer.name},\n\n"
            f"Great news! Your event '{req.event_name}' has received final approval from Students Affairs Dean {dean.name}.\n\n"
            f"With both HOD and Dean endorsements confirmed, your event is now officially PUBLISHED on Campus Flow.\n\n"
            f"Students can now discover your event, register, and receive entry QR tickets. You can manage registrations, payments, attendance, and certificates directly from your Organizer Dashboard.\n\n"
            f"— Campus Flow System"
        )
        SENT_EMAILS.append({'to': organizer.email, 'subject': subject_org, 'body': body_org, 'type': 'EVENT_DEAN_APPROVED_NOTIFY_ORGANIZER'})
        dispatch_email(organizer.email, subject_org, body_org)

    # Notify HOD
    if hod and hod.email:
        subject_hod = f"Event Published: '{req.event_name}' Approved by Dean"
        body_hod = (
            f"Dear {hod.name},\n\n"
            f"The event proposal '{req.event_name}' from your department has been officially APPROVED by Students Affairs Dean {dean.name} and is now published.\n\n"
            f"— Campus Flow System"
        )
        SENT_EMAILS.append({'to': hod.email, 'subject': subject_hod, 'body': body_hod, 'type': 'EVENT_DEAN_APPROVED_NOTIFY_HOD'})
        dispatch_email(hod.email, subject_hod, body_hod)

    logger.info(f"[EMAIL SENT] Event '{req.event_name}' Dean Approved notifications dispatched.")
    return True


def send_event_request_dean_rejected_email(req, organizer, hod, dean, reason=None):
    """Event 8: Dean rejects event -> Organizer and respective HOD."""
    reason_text = f"\nReason: {reason}\n" if reason else ""
    
    # Notify Organizer
    if organizer and organizer.email:
        subject_org = f"Event Proposal Decision: '{req.event_name}'"
        body_org = (
            f"Dear {organizer.name},\n\n"
            f"Your event proposal '{req.event_name}' was reviewed by Students Affairs Dean {dean.name} and was not approved at the college level.{reason_text}\n"
            f"The event has not been published. Details can be viewed in your Organizer Dashboard.\n\n"
            f"— Campus Flow System"
        )
        SENT_EMAILS.append({'to': organizer.email, 'subject': subject_org, 'body': body_org, 'type': 'EVENT_DEAN_REJECTED_NOTIFY_ORGANIZER'})
        dispatch_email(organizer.email, subject_org, body_org)

    # Notify HOD
    if hod and hod.email:
        subject_hod = f"Event Proposal Update: '{req.event_name}' Declined by Dean"
        body_hod = (
            f"Dear {hod.name},\n\n"
            f"The forwarded event proposal '{req.event_name}' was reviewed by Students Affairs Dean {dean.name} and was not approved.{reason_text}\n\n"
            f"— Campus Flow System"
        )
        SENT_EMAILS.append({'to': hod.email, 'subject': subject_hod, 'body': body_hod, 'type': 'EVENT_DEAN_REJECTED_NOTIFY_HOD'})
        dispatch_email(hod.email, subject_hod, body_hod)

    logger.info(f"[EMAIL SENT] Event '{req.event_name}' Dean Rejection notifications dispatched.")
    return True


# ==============================================================================
# ACCOUNT, PAYMENT & CERTIFICATE NOTIFICATION EMAILS
# ==============================================================================

def send_account_registration_email(user):
    """
    Sends a welcome email to newly registered students.
    """
    if not user or not user.email:
        return False

    profile = user.student_profile
    dept = profile.department if profile else 'Campus'
    roll = profile.roll_number if profile else 'N/A'

    subject = "Welcome to Campus Flow! Account Registration Confirmed"
    body = (
        f"Hello {user.name},\n\n"
        f"Welcome to Campus Flow — your central college event management platform!\n\n"
        f"Account Details:\n"
        f"Name: {user.name}\n"
        f"Email: {user.email}\n"
        f"Roll Number: {roll}\n"
        f"Department: {dept}\n\n"
        f"You can now explore campus events, join teams, register for workshops, "
        f"download QR entry passes, and track your certificates.\n\n"
        f"— Campus Flow Team"
    )

    email_record = {
        'to': user.email,
        'subject': subject,
        'body': body,
        'user_id': user.id,
        'type': 'ACCOUNT_REGISTRATION'
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Account welcome to: {user.email}")
    dispatch_email(user.email, subject, body)
    return True


def send_payment_confirmation_email(payment, user, event, registration=None):
    """
    Sends payment confirmation and ticket receipt once payment is verified.
    """
    if not user or not user.email:
        return False

    reg_code = (
        registration.registration_code 
        if registration 
        else (payment.registration.registration_code if payment.registration else 'N/A')
    )
    event_title = event.title if event else 'Campus Event'
    amount = f"₹{payment.amount:.2f}" if payment.amount is not None else "N/A"
    tx_id = payment.transaction_id or 'N/A'
    date_str = event.start_time.strftime('%b %d, %Y %I:%M %p') if (event and event.start_time) else 'N/A'
    venue_str = event.venue if event else 'Campus'

    subject = f"Payment Verified: {event_title} - Ticket #{reg_code}"
    body = (
        f"Hello {user.name},\n\n"
        f"Your payment for '{event_title}' has been successfully verified!\n\n"
        f"Payment Details:\n"
        f"Amount: {amount}\n"
        f"Transaction ID / Ref: {tx_id}\n"
        f"Ticket Code: {reg_code}\n"
        f"Event Date: {date_str}\n"
        f"Venue: {venue_str}\n\n"
        f"Your confirmed entry ticket and QR code pass are now active in your Campus Flow dashboard.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {
        'to': user.email,
        'subject': subject,
        'body': body,
        'payment_id': payment.id,
        'registration_code': reg_code,
        'event_id': event.id if event else None,
        'type': 'PAYMENT_CONFIRMATION'
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Payment confirmation to: {user.email} | Ticket: {reg_code}")
    dispatch_email(user.email, subject, body)
    return True


def send_certificate_ready_email(certificate, user, event):
    """
    Notifies a student that their certificate for an event is available for download.
    """
    if not user or not user.email:
        return False

    event_title = event.title if event else 'Campus Event'
    cert_code = certificate.certificate_code if certificate else 'N/A'

    subject = f"Certificate Available: '{event_title}' - Campus Flow"
    body = (
        f"Hello {user.name},\n\n"
        f"Congratulations! Your certificate for '{event_title}' has been issued and is now ready.\n\n"
        f"Certificate ID: {cert_code}\n"
        f"Event: {event_title}\n\n"
        f"You can view and download your official certificate anytime by logging into Campus Flow "
        f"and navigating to Student Dashboard > Certificates.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {
        'to': user.email,
        'subject': subject,
        'body': body,
        'certificate_code': cert_code,
        'event_id': event.id if event else None,
        'user_id': user.id,
        'type': 'CERTIFICATE_READY'
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Certificate ready notification to: {user.email} | Code: {cert_code}")
    dispatch_email(user.email, subject, body)
    return True

