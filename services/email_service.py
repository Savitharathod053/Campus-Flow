"""
Campus Flow - Email & Notification Service
Handles email delivery for team invitations, responses, and registration confirmations.
"""
import os
import sys
import socket
import smtplib
import logging
import threading
import email.utils
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid, parseaddr
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


def _parse_port(value, default=587):
    """Safely parse port number handling None, whitespace, quotes, and empty strings."""
    if value is None:
        return default
    try:
        return int(str(value).strip().strip("'\""))
    except (ValueError, TypeError):
        return default


def get_mail_config():
    """
    Reads SMTP configuration from Flask current_app.config or environment variables.
    Sanitizes values, removes quotes, and normalizes Google App Passwords.
    """
    config = {}
    if current_app:
        app_cfg = current_app.config
        server = (app_cfg.get('MAIL_SERVER') or os.environ.get('MAIL_SERVER') or 'smtp.gmail.com').strip().strip("'\"")
        port = _parse_port(app_cfg.get('MAIL_PORT') or os.environ.get('MAIL_PORT'), 587)
        use_tls = app_cfg.get('MAIL_USE_TLS')
        if use_tls is None:
            use_tls = os.environ.get('MAIL_USE_TLS', 'True').strip().lower() in ('true', '1', 't', 'yes')
        use_ssl = app_cfg.get('MAIL_USE_SSL')
        if use_ssl is None:
            use_ssl = os.environ.get('MAIL_USE_SSL', 'False').strip().lower() in ('true', '1', 't', 'yes')
        username = (app_cfg.get('MAIL_USERNAME') or os.environ.get('MAIL_USERNAME') or '').strip().strip("'\"")
        password = (app_cfg.get('MAIL_PASSWORD') or os.environ.get('MAIL_PASSWORD') or '').strip().strip("'\"")
        sender = (
            app_cfg.get('MAIL_DEFAULT_SENDER') or 
            os.environ.get('MAIL_DEFAULT_SENDER') or 
            username or 
            'noreply@campusflow.edu'
        ).strip().strip("'\"")
        testing = app_cfg.get('TESTING', False)
        dev_redirect = app_cfg.get('MAIL_DEV_REDIRECT_ENABLED')
        if dev_redirect is None:
            dev_redirect = os.environ.get('MAIL_DEV_REDIRECT_ENABLED', 'True').strip().lower() in ('true', '1', 't', 'yes')
        live_recipient = (app_cfg.get('MAIL_LIVE_TEST_RECIPIENT') or os.environ.get('MAIL_LIVE_TEST_RECIPIENT') or username or 'savitharathod053@gmail.com').strip().strip("'\"")
    else:
        server = (os.environ.get('MAIL_SERVER') or 'smtp.gmail.com').strip().strip("'\"")
        port = _parse_port(os.environ.get('MAIL_PORT'), 587)
        use_tls = os.environ.get('MAIL_USE_TLS', 'True').strip().lower() in ('true', '1', 't', 'yes')
        use_ssl = os.environ.get('MAIL_USE_SSL', 'False').strip().lower() in ('true', '1', 't', 'yes')
        username = (os.environ.get('MAIL_USERNAME') or '').strip().strip("'\"")
        password = (os.environ.get('MAIL_PASSWORD') or '').strip().strip("'\"")
        sender = (
            os.environ.get('MAIL_DEFAULT_SENDER') or 
            username or 
            'noreply@campusflow.edu'
        ).strip().strip("'\"")
        testing = os.environ.get('TESTING', 'False').strip().lower() in ('true', '1')
        dev_redirect = os.environ.get('MAIL_DEV_REDIRECT_ENABLED', 'True').strip().lower() in ('true', '1', 't', 'yes')
        live_recipient = (os.environ.get('MAIL_LIVE_TEST_RECIPIENT') or username or 'savitharathod053@gmail.com').strip().strip("'\"")

    # For Gmail accounts, Google App Passwords are 16 characters (often copied with spaces).
    # Removing internal spaces ensures clean authentication across all deployment environments.
    if ('gmail' in server.lower() or 'google' in server.lower()):
        cleaned_pw = password.replace(' ', '')
        if len(cleaned_pw) == 16:
            password = cleaned_pw

    config['MAIL_SERVER'] = server
    config['MAIL_PORT'] = port
    config['MAIL_USE_TLS'] = use_tls
    config['MAIL_USE_SSL'] = use_ssl
    config['MAIL_USERNAME'] = username
    config['MAIL_PASSWORD'] = password
    config['MAIL_DEFAULT_SENDER'] = sender
    config['TESTING'] = testing
    config['MAIL_DEV_REDIRECT_ENABLED'] = dev_redirect
    config['MAIL_LIVE_TEST_RECIPIENT'] = live_recipient

    return config


def _connect_and_send(server_host, port, use_ssl, use_tls, username, password, sender_envelope, to_email, msg_str, timeout=12):
    """
    Establish an SMTP connection with the specified port and TLS/SSL settings,
    authenticates, and sends the message.
    """
    if use_ssl or port == 465:
        server = smtplib.SMTP_SSL(server_host, port, timeout=timeout)
    else:
        server = smtplib.SMTP(server_host, port, timeout=timeout)
        if use_tls:
            server.starttls()

    server.login(username, password)
    server.sendmail(sender_envelope, [to_email], msg_str)
    try:
        server.quit()
    except Exception:
        pass
    return True


def _send_smtp_worker(to_email, subject, body_text, body_html=None, config=None):
    """
    Worker function executed to transmit email via SMTP.
    Includes automated dual-port failover (Port 587 STARTTLS <-> Port 465 SSL)
    to handle cloud platform firewall restrictions (e.g. Render, AWS, Linode).
    """
    if not config:
        config = get_mail_config()

    server_host = config.get('MAIL_SERVER', 'smtp.gmail.com')
    port = _parse_port(config.get('MAIL_PORT'), 587)
    use_tls = config.get('MAIL_USE_TLS', True)
    use_ssl = config.get('MAIL_USE_SSL', False)
    username = config.get('MAIL_USERNAME', '')
    password = config.get('MAIL_PASSWORD', '')
    sender = config.get('MAIL_DEFAULT_SENDER') or username or 'noreply@campusflow.edu'

    if not username or not password:
        logger.warning(
            f"[EMAIL NOT SENT - MISSING CREDENTIALS] To: {to_email} | Subject: '{subject}'. "
            "Please configure MAIL_USERNAME and MAIL_PASSWORD in production environment variables."
        )
        return False

    # Extract bare email for RFC 5321 MAIL FROM envelope and retain full display name for RFC 5322 header
    sender_display = sender.strip().strip("'\"")
    envelope_from = parseaddr(sender_display)[1] or username

    # Determine primary and fallback port strategies
    primary_ssl = use_ssl or (port == 465)
    primary_strategy = {
        'port': port,
        'use_ssl': primary_ssl,
        'use_tls': use_tls and not primary_ssl
    }
    # If primary is 587 TLS, fallback is 465 SSL; if primary is 465 SSL, fallback is 587 TLS
    fallback_strategy = {
        'port': 465 if not primary_ssl else 587,
        'use_ssl': not primary_ssl,
        'use_tls': primary_ssl
    }

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = sender_display
        msg['To'] = to_email
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid(domain='campusflow.edu')

        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))
        if body_html:
            msg.attach(MIMEText(body_html, 'html', 'utf-8'))
        msg_str = msg.as_string()

        # 1. Attempt primary port connection
        try:
            _connect_and_send(
                server_host=server_host,
                port=primary_strategy['port'],
                use_ssl=primary_strategy['use_ssl'],
                use_tls=primary_strategy['use_tls'],
                username=username,
                password=password,
                sender_envelope=envelope_from,
                to_email=to_email,
                msg_str=msg_str,
                timeout=10
            )
            logger.info(f"[EMAIL DELIVERED] To: {to_email} | Subject: '{subject}' via {server_host}:{primary_strategy['port']}")
            return True
        except smtplib.SMTPAuthenticationError as auth_err:
            logger.error(
                f"[EMAIL AUTHENTICATION ERROR] Could not authenticate with {server_host} for user {username}. "
                f"If using Gmail, ensure a 16-character Google App Password is used without spaces: {auth_err}"
            )
            return False
        except (socket.timeout, TimeoutError, ConnectionRefusedError, OSError, smtplib.SMTPConnectError, smtplib.SMTPException) as conn_err:
            logger.warning(
                f"[SMTP FAILOVER] Primary connection to {server_host}:{primary_strategy['port']} failed ({conn_err}). "
                f"Attempting cloud failover to port {fallback_strategy['port']} (SSL={fallback_strategy['use_ssl']})..."
            )
            # 2. Attempt fallback port connection
            try:
                _connect_and_send(
                    server_host=server_host,
                    port=fallback_strategy['port'],
                    use_ssl=fallback_strategy['use_ssl'],
                    use_tls=fallback_strategy['use_tls'],
                    username=username,
                    password=password,
                    sender_envelope=envelope_from,
                    to_email=to_email,
                    msg_str=msg_str,
                    timeout=12
                )
                logger.info(f"[EMAIL DELIVERED VIA FAILOVER] To: {to_email} | Subject: '{subject}' via {server_host}:{fallback_strategy['port']}")
                return True
            except Exception as fallback_err:
                logger.error(f"[EMAIL DELIVERY ERROR] Failed on both primary and fallback ports for {server_host}: {fallback_err}")
                return False

    except Exception as exc:
        logger.error(f"[EMAIL DELIVERY ERROR] Unexpected error sending email to {to_email}: {exc}")
        return False


def dispatch_email(to_email, subject, body_text, body_html=None, sync=False):
    """
    Dispatches email. In test mode, records to SENT_EMAILS and bypasses network I/O.
    In live mode with credentials, transmits via SMTP (using a non-daemon thread to ensure WSGI
    lifecycle does not prematurely terminate socket I/O before completion).
    Supports live routing for development and demo environments so emails to @college.edu
    are delivered directly to the configured live email inbox.
    """
    if not to_email:
        return False

    cfg = get_mail_config()

    # Record to in-memory store for bare dispatch_email calls if not already recorded
    if not SENT_EMAILS or (SENT_EMAILS[-1].get('to') != to_email or SENT_EMAILS[-1].get('subject') != subject):
        SENT_EMAILS.append({
            'to': to_email,
            'subject': subject,
            'body': body_text,
            'html': body_html
        })

    if cfg.get('TESTING', False):
        return True

    if not cfg.get('MAIL_USERNAME') or not cfg.get('MAIL_PASSWORD'):
        logger.warning(
            f"[EMAIL SIMULATED - CREDENTIALS UNSET] To: {to_email} | Subject: '{subject}'. "
            "Configure MAIL_USERNAME and MAIL_PASSWORD in your hosting environment variables (e.g. Render Dashboard)."
        )
        return True

    # Live routing / forward to real mailbox
    live_target = (
        cfg.get('MAIL_OVERRIDE_RECIPIENT') or 
        cfg.get('MAIL_LIVE_TEST_RECIPIENT') or 
        cfg.get('MAIL_USERNAME') or 
        'savitharathod053@gmail.com'
    ).strip()

    route_to_live = (
        cfg.get('MAIL_DEV_REDIRECT_ENABLED', True) or
        os.environ.get('MAIL_DEV_REDIRECT_ENABLED', 'True').strip().lower() in ('true', '1', 't', 'yes')
    )

    delivery_target = to_email
    delivery_subject = subject
    delivery_body_text = body_text
    delivery_body_html = body_html

    # Check if target is a dummy or non-routable domain (e.g. @college.edu, @example.com)
    is_dummy_domain = any(to_email.lower().endswith(dom) for dom in ('@college.edu', '@example.com', '@test.com', '.local', '.invalid'))
    
    if route_to_live and (is_dummy_domain or os.environ.get('MAIL_ROUTE_ALL_TO_LIVE', 'False').strip().lower() in ('true', '1', 'yes')):
        delivery_target = live_target
        delivery_subject = f"[{to_email}] {subject}"
        banner_text = (
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"CAMPUS FLOW - LIVE EMAIL ROUTING\n"
            f"Intended Recipient: {to_email}\n"
            f"Delivered To Live Inbox: {live_target}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        delivery_body_text = banner_text + (body_text or '')
        if delivery_body_html:
            banner_html = (
                f"<div style='background:#f8fafc;border-left:4px solid #4f46e5;padding:12px 16px;margin-bottom:18px;border-radius:6px;font-family:sans-serif;font-size:13px;color:#334155;'>"
                f"<strong style='color:#4f46e5;'>[Campus Flow Live Routing]</strong> "
                f"Intended for <code>{to_email}</code> &bull; Delivered to Live Inbox: <strong style='color:#059669;'>{live_target}</strong>"
                f"</div>"
            )
            delivery_body_html = banner_html + delivery_body_html

    if sync:
        return _send_smtp_worker(delivery_target, delivery_subject, delivery_body_text, delivery_body_html, config=cfg)
    else:
        thread = threading.Thread(
            target=_send_smtp_worker,
            args=(delivery_target, delivery_subject, delivery_body_text, delivery_body_html, cfg),
            daemon=False
        )
        thread.start()
        return True


def test_smtp_connection(config=None):
    """
    Diagnostic tool to verify SMTP server connectivity and authentication.
    Tests primary port and automatically attempts fallback port if needed.
    Returns (success: bool, message: str).
    """
    if not config:
        config = get_mail_config()

    server_host = config.get('MAIL_SERVER', 'smtp.gmail.com')
    port = _parse_port(config.get('MAIL_PORT'), 587)
    use_tls = config.get('MAIL_USE_TLS', True)
    use_ssl = config.get('MAIL_USE_SSL', False)
    username = config.get('MAIL_USERNAME', '')
    password = config.get('MAIL_PASSWORD', '')

    if not username or not password:
        return False, "MAIL_USERNAME or MAIL_PASSWORD is not set in environment variables. Add them in your hosting dashboard."

    primary_ssl = use_ssl or (port == 465)
    primary_tls = use_tls and not primary_ssl
    fallback_port = 465 if not primary_ssl else 587
    fallback_ssl = not primary_ssl
    fallback_tls = primary_ssl

    try:
        if primary_ssl:
            server = smtplib.SMTP_SSL(server_host, port, timeout=10)
        else:
            server = smtplib.SMTP(server_host, port, timeout=10)
            if primary_tls:
                server.starttls()

        server.login(username, password)
        server.quit()
        protocol_str = "SSL" if primary_ssl else "STARTTLS"
        return True, f"Successfully connected and authenticated with {server_host}:{port} via {protocol_str} as {username}."
    except smtplib.SMTPAuthenticationError as auth_err:
        return False, f"SMTP Authentication failed for '{username}'. Check that your 16-character Google App Password is correct: {auth_err}"
    except Exception as primary_err:
        try:
            if fallback_ssl:
                server = smtplib.SMTP_SSL(server_host, fallback_port, timeout=10)
            else:
                server = smtplib.SMTP(server_host, fallback_port, timeout=10)
                if fallback_tls:
                    server.starttls()

            server.login(username, password)
            server.quit()
            protocol_str = "SSL" if fallback_ssl else "STARTTLS"
            return True, (
                f"Primary port {port} encountered ({primary_err}), but FAILOVER SUCCEEDED: "
                f"Connected and authenticated with {server_host}:{fallback_port} via {protocol_str} as {username}."
            )
        except Exception as fallback_err:
            return False, (
                f"SMTP connection failed on primary port {port} ({primary_err}) "
                f"and fallback port {fallback_port} ({fallback_err}). "
                "Cloud firewall may be restricting outbound SMTP traffic."
            )


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


# ==============================================================================
# ADDITIONAL EXTENDED WORKFLOW EMAIL NOTIFICATIONS
# ==============================================================================

def send_organizer_application_received_email(user, profile_or_req=None, assigned_admin_name=None):
    """
    Sends confirmation to a student/organizer applicant that their organizer application was received.
    """
    if not user or not user.email:
        return False

    reviewer_str = f"your department faculty coordinator ({assigned_admin_name})" if assigned_admin_name else "your department HOD"
    subject = "Organizer Application Received — Campus Flow"
    body = (
        f"Hello {user.name},\n\n"
        f"We have received your application to become an Event Organizer on Campus Flow.\n\n"
        f"Your request has been forwarded to {reviewer_str} for review and approval.\n"
        f"You will receive another notification as soon as a decision is made on your application.\n\n"
        f"Thank you for taking the initiative to lead campus activities!\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {'to': user.email, 'subject': subject, 'body': body, 'type': 'ORGANIZER_APPLICATION_CONFIRMATION'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Organizer application confirmation to: {user.email}")
    dispatch_email(user.email, subject, body)
    return True


def send_organizer_registration_faculty_notice_email(applicant_user, faculty_user, department_name, profile=None):
    """
    Sends notification to department faculty/HOD that a new organizer registered and is awaiting approval.
    """
    if not faculty_user or not faculty_user.email:
        return False

    roll = profile.roll_number if (profile and profile.roll_number) else 'N/A'
    org_name = profile.organization_name if (profile and profile.organization_name) else 'Campus Club/Society'

    subject = f"Action Required: New Organizer Registration - {applicant_user.name} ({department_name})"
    body = (
        f"Dear {faculty_user.name},\n\n"
        f"A new student organizer has registered and is awaiting your review and approval:\n\n"
        f"Applicant Name: {applicant_user.name}\n"
        f"Roll Number: {roll}\n"
        f"Email: {applicant_user.email}\n"
        f"Department: {department_name}\n"
        f"Organization/Club: {org_name}\n\n"
        f"Please log in to your Campus Flow dashboard to review and approve or reject this application.\n\n"
        f"— Campus Flow System"
    )

    email_record = {'to': faculty_user.email, 'subject': subject, 'body': body, 'type': 'ORGANIZER_REGISTRATION_FACULTY_NOTICE'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Organizer notice to faculty: {faculty_user.email}")
    dispatch_email(faculty_user.email, subject, body)
    return True


def send_event_request_submitted_organizer_confirm_email(req, organizer, hod, dept):
    """
    Sends confirmation to the organizer that their event proposal was submitted and is under HOD review.
    """
    if not organizer or not organizer.email:
        return False

    hod_name = hod.name if hod else "your Department HOD"
    dept_name = dept.name if dept else (req.category or "Department")

    subject = f"Proposal Submitted: '{req.event_name}' - Pending HOD Review"
    body = (
        f"Hello {organizer.name},\n\n"
        f"Your event proposal '{req.event_name}' has been successfully submitted on Campus Flow!\n\n"
        f"Event Details:\n"
        f"Event Name: {req.event_name}\n"
        f"Category: {req.category}\n"
        f"Proposed Date: {req.proposed_event_date}\n"
        f"Venue: {req.venue}\n"
        f"Department: {dept_name}\n\n"
        f"Your proposal is currently under review by {hod_name}. "
        f"Once endorsed, it will be forwarded to the Students Affairs Dean for final college-level publication clearance.\n\n"
        f"You can track the live status anytime on your Organizer Dashboard.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {'to': organizer.email, 'subject': subject, 'body': body, 'type': 'EVENT_SUBMISSION_CONFIRMATION_ORGANIZER'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Event submission confirmation to organizer: {organizer.email}")
    dispatch_email(organizer.email, subject, body)
    return True


def send_payment_proof_submitted_email(payment, student, event, organizer):
    """
    Sends notification to event organizer that a student submitted payment proof,
    and sends acknowledgment to the student.
    """
    amount_str = f"₹{payment.amount:.2f}" if payment.amount is not None else "N/A"
    tx_str = payment.transaction_id or "N/A"
    roll_str = student.student_profile.roll_number if (student and student.student_profile and student.student_profile.roll_number) else "N/A"

    # 1. Notify Organizer
    if organizer and organizer.email:
        subject_org = f"Payment Verification Required: {student.name} - {event.title}"
        body_org = (
            f"Hello {organizer.name},\n\n"
            f"A student has submitted payment proof for your event '{event.title}':\n\n"
            f"Student: {student.name} (Roll: {roll_str}, Email: {student.email})\n"
            f"Amount: {amount_str}\n"
            f"Transaction ID / Ref: {tx_str}\n\n"
            f"Please log in to your Organizer Dashboard > Payment Verification to verify the receipt and issue the student's entry ticket.\n\n"
            f"— Campus Flow Events Team"
        )
        SENT_EMAILS.append({'to': organizer.email, 'subject': subject_org, 'body': body_org, 'type': 'PAYMENT_PROOF_SUBMITTED_ORGANIZER'})
        logger.info(f"[EMAIL SENT] Payment proof notice to organizer: {organizer.email}")
        dispatch_email(organizer.email, subject_org, body_org)

    # 2. Acknowledge Student
    if student and student.email:
        subject_std = f"Payment Proof Received: '{event.title}' - Pending Verification"
        body_std = (
            f"Hello {student.name},\n\n"
            f"We have received your payment proof for '{event.title}'.\n\n"
            f"Payment Summary:\n"
            f"Event: {event.title}\n"
            f"Amount Submitted: {amount_str}\n"
            f"Reference / UTR: {tx_str}\n\n"
            f"The event organizer will review your payment receipt. "
            f"Once verified, your confirmed QR ticket will automatically be activated in your dashboard.\n\n"
            f"— Campus Flow Events Team"
        )
        SENT_EMAILS.append({'to': student.email, 'subject': subject_std, 'body': body_std, 'type': 'PAYMENT_PROOF_SUBMITTED_STUDENT'})
        logger.info(f"[EMAIL SENT] Payment proof acknowledgment to student: {student.email}")
        dispatch_email(student.email, subject_std, body_std)

    return True


def send_payment_rejected_email(payment, student, event, reason=None):
    """
    Sends notification to student that their payment proof was rejected by the organizer.
    """
    if not student or not student.email:
        return False

    reason_str = reason or payment.verification_reason or "Payment screenshot could not be validated."
    amount_str = f"₹{payment.amount:.2f}" if payment.amount is not None else "N/A"
    tx_str = payment.transaction_id or "N/A"

    subject = f"Payment Verification Update: '{event.title}'"
    body = (
        f"Hello {student.name},\n\n"
        f"Your submitted payment proof for the event '{event.title}' was reviewed by the event organizer and was NOT approved.\n\n"
        f"Reason for Rejection:\n{reason_str}\n\n"
        f"Submission Details:\n"
        f"Amount: {amount_str}\n"
        f"Transaction Reference: {tx_str}\n\n"
        f"Your registration remains active in 'Pending Payment' status. "
        f"Please log in to your Campus Flow dashboard to re-upload a clear, valid payment proof or contact the organizer.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {'to': student.email, 'subject': subject, 'body': body, 'type': 'PAYMENT_REJECTED'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Payment rejected notification to: {student.email}")
    dispatch_email(student.email, subject, body)
    return True


def send_member_invitation_response_member_email(recipient_email, recipient_name, team, event, response_type):
    """
    Sends confirmation to the invited student when they accept or decline a team invitation.
    """
    if not recipient_email:
        return False

    name = recipient_name or recipient_email
    if response_type == 'ACCEPTED':
        subject = f"Team Joined: '{team.team_name}' for '{event.title}'"
        body = (
            f"Hello {name},\n\n"
            f"You have successfully joined the team '{team.team_name}' for '{event.title}'!\n\n"
            f"Team Lead: {team.lead.name if team.lead else 'Team Lead'}\n"
            f"Event Date: {event.start_time.strftime('%b %d, %Y %I:%M %p')}\n"
            f"Venue: {event.venue}\n\n"
            f"You can view your team details and teammates on your Campus Flow dashboard.\n\n"
            f"— Campus Flow Events Team"
        )
    else:
        subject = f"Invitation Declined: '{team.team_name}' for '{event.title}'"
        body = (
            f"Hello {name},\n\n"
            f"You have declined the invitation to join team '{team.team_name}' for '{event.title}'.\n\n"
            f"If this was unintentional, please ask the team lead ({team.lead.name if team.lead else 'lead'}) to send you a new invitation.\n\n"
            f"— Campus Flow Events Team"
        )

    email_record = {'to': recipient_email, 'subject': subject, 'body': body, 'type': f'MEMBER_CONFIRMATION_{response_type}'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Member response confirmation to: {recipient_email}")
    dispatch_email(recipient_email, subject, body)
    return True


def send_attendance_marked_email(student, event, session, att_record):
    """
    Sends notification to student confirming that their attendance was recorded.
    """
    if not student or not student.email:
        return False

    session_name = session.session_name if session else "General Session"
    from services.timezone_service import format_ist_datetime, get_current_ist_time
    time_str = format_ist_datetime(att_record.scanned_at) if (att_record and att_record.scanned_at) else format_ist_datetime(get_current_ist_time())
    event_title = event.title if event else "Campus Event"

    subject = f"Attendance Confirmed: {event_title} ({session_name})"
    body = (
        f"Hello {student.name},\n\n"
        f"Your attendance has been recorded for '{event_title}'.\n\n"
        f"Session: {session_name}\n"
        f"Status: PRESENT\n"
        f"Recorded At: {time_str}\n"
        f"Venue: {event.venue if event else 'Campus'}\n\n"
        f"You can monitor your attendance percentages and track eligibility for certificates "
        f"in your Campus Flow student dashboard.\n\n"
        f"— Campus Flow Events Team"
    )

    email_record = {'to': student.email, 'subject': subject, 'body': body, 'type': 'ATTENDANCE_RECORDED'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Attendance marked confirmation to: {student.email}")
    dispatch_email(student.email, subject, body)
    return True


def send_event_admin_action_email(event, organizer, action, reason=None):
    """
    Sends notification to organizer when Super Admin approves, rejects, or cancels an event.
    """
    if not organizer or not organizer.email:
        return False

    reason_str = f"\nReason: {reason}\n" if reason else ""
    subject = f"Event Status Update: '{event.title}' has been {action}"
    body = (
        f"Hello {organizer.name},\n\n"
        f"Your event '{event.title}' status has been updated to {action} by the System Administrator.{reason_str}\n"
        f"You can review your event status and details in your Organizer Dashboard.\n\n"
        f"— Campus Flow Administration"
    )

    email_record = {'to': organizer.email, 'subject': subject, 'body': body, 'type': f'EVENT_ADMIN_{action}'}
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Event admin action to organizer: {organizer.email}")
    dispatch_email(organizer.email, subject, body)
    return True


def send_empty_slots_hod_email(hod, event, empty_slots, total_capacity, confirmed_count):
    """
    Sends an email notification to the responsible HOD when an event starts with empty slots.
    """
    if not hod or not hod.email:
        return False

    from services.timezone_service import format_ist_datetime
    start_time_str = format_ist_datetime(event.start_time) if event.start_time else "N/A"
    hod_display = hod.name if (hod.name and hod.name.strip().lower().startswith("dr.")) else f"Dr. {hod.name if hod else 'HOD'}"

    subject = f"{empty_slots} Empty Slots - {event.title}"
    body = (
        f"Hello {hod_display},\n\n"
        f"The event \"{event.title}\" has officially started.\n\n"
        f"Event Details:\n"
        f"- Department: {event.department}\n"
        f"- Start Time: {start_time_str}\n"
        f"- Total Capacity: {total_capacity}\n"
        f"- Confirmed Registrations: {confirmed_count}\n"
        f"- Empty Slots Remaining: {empty_slots}\n\n"
        f"Please review the event status in your Campus Flow dashboard.\n\n"
        f"Campus Flow Event Monitoring System"
    )

    email_record = {
        'to': hod.email,
        'subject': subject,
        'body': body,
        'type': 'EVENT_CAPACITY_ALERT'
    }
    SENT_EMAILS.append(email_record)
    logger.info(f"[EMAIL SENT] Empty slots alert to HOD {hod.email} for event {event.id}")
    dispatch_email(hod.email, subject, body)
    return True


