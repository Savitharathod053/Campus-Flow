"""
Campus Flow - Live Email Diagnostic CLI Tool
Usage:
    python test_live_email.py
    python test_live_email.py --to recipient@college.edu
"""
import os
import sys
import socket
import argparse
from datetime import datetime
from dotenv import load_dotenv

# Load local .env if available
load_dotenv()

from services.email_service import get_mail_config, test_smtp_connection, dispatch_email

def mask_secret(secret):
    if not secret:
        return "(not set)"
    if len(secret) <= 4:
        return "****"
    return secret[:2] + ("*" * (len(secret) - 4)) + secret[-2:]

def check_tcp_port(host, port, timeout=5):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception as e:
        return False

def run_diagnostics(recipient=None):
    print("=" * 70)
    print(" CAMPUS FLOW - PRODUCTION LIVE EMAIL DIAGNOSTIC TOOL")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python:    {sys.version.split()[0]} on {sys.platform}")
    print("-" * 70)

    # 1. Environment & Configuration Check
    cfg = get_mail_config()
    server = cfg.get('MAIL_SERVER', 'smtp.gmail.com')
    port = cfg.get('MAIL_PORT', 587)
    use_tls = cfg.get('MAIL_USE_TLS', True)
    use_ssl = cfg.get('MAIL_USE_SSL', False)
    username = cfg.get('MAIL_USERNAME', '')
    password = cfg.get('MAIL_PASSWORD', '')
    sender = cfg.get('MAIL_DEFAULT_SENDER', '')

    print("[1] Configuration Inspection:")
    print(f"    MAIL_SERVER:         {server}")
    print(f"    MAIL_PORT:           {port}")
    print(f"    MAIL_USE_TLS:        {use_tls}")
    print(f"    MAIL_USE_SSL:        {use_ssl}")
    print(f"    MAIL_USERNAME:       {username or '(MISSING)'}")
    print(f"    MAIL_PASSWORD:       {mask_secret(password)} (Length: {len(password)})")
    print(f"    MAIL_DEFAULT_SENDER: {sender or '(MISSING)'}")

    if not username or not password:
        print("\n[!] CRITICAL ERROR: MAIL_USERNAME or MAIL_PASSWORD is not set!")
        print("    If deployed on Render/Railway/Heroku, you MUST add these variables in your Dashboard:")
        print("    - MAIL_SERVER = smtp.gmail.com")
        print("    - MAIL_PORT = 587")
        print("    - MAIL_USE_TLS = True")
        print("    - MAIL_USE_SSL = False")
        print("    - MAIL_USERNAME = your_gmail_address@gmail.com")
        print("    - MAIL_PASSWORD = your_16_character_app_password")
        print("    - MAIL_DEFAULT_SENDER = Campus Flow <your_gmail_address@gmail.com>")
        return False

    # 2. Outbound Network Connectivity Check
    print("\n[2] Outbound Network & Port Reachability:")
    port_587_open = check_tcp_port(server, 587)
    port_465_open = check_tcp_port(server, 465)
    print(f"    Port 587 (STARTTLS): {'[OPEN] Reached' if port_587_open else '[BLOCKED/TIMEOUT] Could not connect'}")
    print(f"    Port 465 (SSL):      {'[OPEN] Reached' if port_465_open else '[BLOCKED/TIMEOUT] Could not connect'}")

    if not port_587_open and not port_465_open:
        print("\n[!] WARNING: Both ports 587 and 465 appear unreachable from this host.")
        print("    Your cloud provider or hosting firewall may be blocking outbound SMTP connections.")

    # 3. SMTP Handshake & Authentication Test
    print("\n[3] SMTP Authentication & Failover Handshake:")
    success, message = test_smtp_connection(cfg)
    if success:
        print(f"    [SUCCESS] {message}")
    else:
        print(f"    [FAILED] {message}")
        print("\nTroubleshooting Tips:")
        print("1. For Gmail, you MUST use an App Password (not your normal Google account password).")
        print("   Generate one at: https://myaccount.google.com/apppasswords")
        print("2. If deployed on Render and Port 587 is blocked, set:")
        print("   MAIL_PORT=465")
        print("   MAIL_USE_SSL=True")
        print("   MAIL_USE_TLS=False")
        return False

    # 4. Live Dispatch Test
    target_recipient = recipient or username
    print(f"\n[4] Live Email Transmission Test:")
    print(f"    Sending live test message to: {target_recipient}...")

    subject = "Campus Flow - Production Live Email Confirmation"
    body = (
        f"Hello,\n\n"
        f"This is a confirmation test from Campus Flow.\n"
        f"Dispatched at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Server: {server}:{port}\n"
        f"Sender: {sender}\n\n"
        f"If you are reading this email, your live email delivery system is functioning 100% properly!\n\n"
        f"— Campus Flow System"
    )

    sent = dispatch_email(target_recipient, subject, body, sync=True)
    if sent:
        print(f"    [DELIVERED] Test email transmitted successfully to {target_recipient}!")
        print("=" * 70)
        print(" VERDICT: Live email is working properly!")
        print("=" * 70)
        return True
    else:
        print(f"    [FAILED] Email delivery failed. Check application logs.")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Campus Flow Live Email Diagnostic")
    parser.add_argument("--to", help="Target email recipient for live test", default=None)
    args = parser.parse_args()
    ok = run_diagnostics(args.to)
    sys.exit(0 if ok else 1)
