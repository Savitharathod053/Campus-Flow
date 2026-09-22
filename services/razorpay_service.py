import hmac
import hashlib
import logging
from datetime import datetime
from flask import current_app, url_for
from models import db, Payment, PaymentStatus, EventRegistration, RegistrationStatus, Event, User
from services.qr_service import generate_ticket_qr

logger = logging.getLogger("CampusFlow.Razorpay")


def get_razorpay_client():
    """
    Initializes and returns the official Razorpay Client instance using
    configured Test Mode or Live credentials.
    """
    key_id = current_app.config.get('RAZORPAY_KEY_ID')
    key_secret = current_app.config.get('RAZORPAY_KEY_SECRET')

    if not key_id or not key_secret:
        raise ValueError("Razorpay Key ID and Secret must be configured in settings.")

    try:
        import razorpay
        return razorpay.Client(auth=(key_id, key_secret))
    except ImportError:
        logger.error("razorpay package is not installed. Please run pip install razorpay.")
        raise


def create_razorpay_order(registration, amount=None, currency=None, notes=None):
    """
    Creates a unique payment order on Razorpay for a student registration.
    Amount is converted to paise (e.g. ₹100 -> 10000 paise).
    Persists or updates the Payment record in PENDING status.
    """
    if not registration or not registration.event:
        raise ValueError("Valid registration and event are required to create an order.")

    event = registration.event
    if amount is None:
        amount = float(event.registration_fee or 0.0)

    if amount <= 0:
        raise ValueError("Registration fee must be greater than zero for Razorpay checkout.")

    currency = currency or current_app.config.get('RAZORPAY_CURRENCY', 'INR')
    amount_paise = int(round(amount * 100))

    receipt = registration.registration_code
    order_notes = {
        'registration_code': registration.registration_code,
        'registration_id': str(registration.id),
        'event_id': str(event.id),
        'event_title': str(event.title)[:40],
        'student_id': str(registration.student_id),
        'student_name': str(registration.student.name if registration.student else '')[:40]
    }
    if notes and isinstance(notes, dict):
        order_notes.update(notes)

    client = get_razorpay_client()
    try:
        order_data = {
            'amount': amount_paise,
            'currency': currency,
            'receipt': receipt,
            'notes': order_notes
        }
        razorpay_order = client.order.create(data=order_data)
        order_id = razorpay_order.get('id')
    except Exception as exc:
        logger.error(f"Failed to create Razorpay order for registration {registration.id}: {exc}", exc_info=True)
        raise

    # Find existing payment record or create a new one
    payment = Payment.query.filter_by(registration_id=registration.id).first()
    if payment:
        payment.razorpay_order_id = order_id
        payment.amount = amount
        payment.currency = currency
        payment.payment_method = 'RAZORPAY'
        payment.status = PaymentStatus.PENDING
        payment.notes = f"Razorpay Order {order_id} created at {datetime.utcnow().isoformat()}"
    else:
        payment = Payment(
            registration_id=registration.id,
            team_id=registration.team_id,
            event_id=event.id,
            student_id=registration.student_id,
            organizer_id=event.organizer_id,
            amount=amount,
            currency=currency,
            razorpay_order_id=order_id,
            payment_method='RAZORPAY',
            status=PaymentStatus.PENDING,
            notes=f"Razorpay Order {order_id} created at {datetime.utcnow().isoformat()}"
        )
        db.session.add(payment)

    db.session.commit()

    return {
        'order_id': order_id,
        'amount': amount_paise,
        'amount_display': amount,
        'currency': currency,
        'key_id': current_app.config.get('RAZORPAY_KEY_ID'),
        'receipt': receipt,
        'event_title': event.title,
        'student_name': registration.student.name if registration.student else '',
        'student_email': registration.student.email if registration.student else '',
        'student_phone': getattr(registration.student.student_profile, 'phone', '') if (registration.student and registration.student.student_profile) else ''
    }


def verify_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """
    Cryptographically verifies the authenticity of the Razorpay checkout response.
    Computes HMAC-SHA256(order_id + '|' + payment_id, secret) and compares in constant time.
    """
    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return False

    secret = current_app.config.get('RAZORPAY_KEY_SECRET', '')
    if not secret:
        logger.error("RAZORPAY_KEY_SECRET is not configured. Cannot verify payment signature.")
        return False

    msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
    key = secret.encode('utf-8')
    expected_signature = hmac.new(key, msg, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_signature, razorpay_signature)


def verify_webhook_signature(raw_body, webhook_signature):
    """
    Verifies that an incoming webhook payload originated directly from Razorpay servers.
    Computes HMAC-SHA256(raw_body, webhook_secret) and compares in constant time.
    """
    if not raw_body or not webhook_signature:
        return False

    secret = current_app.config.get('RAZORPAY_WEBHOOK_SECRET', '')
    if not secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET is not configured.")
        return False

    if isinstance(raw_body, str):
        raw_body = raw_body.encode('utf-8')

    key = secret.encode('utf-8')
    expected_signature = hmac.new(key, raw_body, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_signature, webhook_signature)


def process_successful_payment(razorpay_order_id, razorpay_payment_id, razorpay_signature=None, webhook_event_id=None):
    """
    Reconciles and confirms a paid transaction idempotently:
    1. Validates Payment record.
    2. If already confirmed, returns safely (idempotent duplicate guard).
    3. Updates Payment status to VERIFIED with audit timestamps and transaction IDs.
    4. Confirms EventRegistration status and generates ticket QR.
    5. Dispatches notifications and confirmation email.
    """
    payment = None
    if razorpay_order_id:
        payment = Payment.query.filter_by(razorpay_order_id=razorpay_order_id).first()

    if not payment and razorpay_payment_id:
        payment = Payment.query.filter_by(razorpay_payment_id=razorpay_payment_id).first()

    if not payment:
        logger.error(f"Cannot find payment record for order_id={razorpay_order_id} or payment_id={razorpay_payment_id}")
        return None, False, "Payment record not found."

    registration = payment.registration
    if not registration:
        logger.error(f"No registration linked to payment id={payment.id}")
        return payment, False, "Registration not found."

    # Idempotency check: if already verified and registration confirmed, return immediately
    if payment.is_verified and registration.is_confirmed and registration.qr_code_image:
        logger.info(f"Payment {payment.id} already verified and registration {registration.id} confirmed. Skipping redundant processing.")
        return payment, True, "Payment already verified (idempotent)."

    # Update payment details
    payment.razorpay_payment_id = razorpay_payment_id
    payment.transaction_id = razorpay_payment_id
    if razorpay_signature:
        payment.razorpay_signature = razorpay_signature
    if webhook_event_id:
        payment.webhook_event_id = webhook_event_id
    payment.payment_method = 'RAZORPAY'
    payment.status = PaymentStatus.VERIFIED
    payment.razorpay_status = 'captured'
    payment.verified_at = datetime.utcnow()
    payment.verification_reason = "Payment automatically verified via Razorpay."

    audit_entry = f"\n[Razorpay Auto-Verify {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}]: Payment ID={razorpay_payment_id}, Order ID={razorpay_order_id}"
    payment.notes = (payment.notes or '') + audit_entry

    # Confirm Registration and generate Entry Ticket QR
    registration.status = RegistrationStatus.CONFIRMED
    if not registration.qr_code_image:
        registration.qr_code_image = generate_ticket_qr(registration.registration_code)

    # Dispatches in-app notification & confirmation email
    try:
        from services.notification_service import create_notification
        from models.notification import NotificationType
        from services.email_service import send_registration_confirmation_email

        event = registration.event
        user = registration.student

        if user and event:
            create_notification(
                user_id=user.id,
                title=f"Payment Verified & Ticket Ready: {event.title}",
                message=f"Your payment of ₹{payment.amount:.2f} for '{event.title}' was verified via Razorpay (Txn: {razorpay_payment_id}). Your entry pass ticket #{registration.registration_code} is ready!",
                notification_type=NotificationType.SYSTEM,
                link=url_for('student.ticket', code=registration.registration_code)
            )

            # Notify Organizer as well
            if event.organizer_id:
                create_notification(
                    user_id=event.organizer_id,
                    title=f"Payment Auto-Reconciled: {user.name}",
                    message=f"Student {user.name} completed online Razorpay fee of ₹{payment.amount:.2f} for '{event.title}' (Txn: {razorpay_payment_id}).",
                    notification_type=NotificationType.SYSTEM,
                    link=url_for('organizer.payment_verification', event_id=event.id)
                )

            # Send full confirmation email
            send_registration_confirmation_email(registration, user, event)
    except Exception as exc:
        logger.warning(f"Could not dispatch payment confirmation notifications: {exc}")

    db.session.commit()
    logger.info(f"Payment {payment.id} verified and registration {registration.id} confirmed successfully.")
    return payment, True, "Payment successfully verified and registration confirmed."


def process_failed_payment(razorpay_order_id, razorpay_payment_id=None, failure_reason=None, webhook_event_id=None):
    """
    Records failed Razorpay payments for auditing and student troubleshooting.
    """
    payment = None
    if razorpay_order_id:
        payment = Payment.query.filter_by(razorpay_order_id=razorpay_order_id).first()

    if not payment and razorpay_payment_id:
        payment = Payment.query.filter_by(razorpay_payment_id=razorpay_payment_id).first()

    if not payment:
        logger.warning(f"Failed payment record not found for order_id={razorpay_order_id}")
        return None

    # Do not overwrite already verified payments
    if payment.is_verified:
        return payment

    payment.status = PaymentStatus.PAYMENT_VERIFICATION_FAILED
    payment.razorpay_status = 'failed'
    payment.failure_reason = failure_reason or "Payment failed or was cancelled by user."
    if razorpay_payment_id:
        payment.razorpay_payment_id = razorpay_payment_id
    if webhook_event_id:
        payment.webhook_event_id = webhook_event_id

    db.session.commit()
    logger.info(f"Recorded failed payment {payment.id} with reason: {failure_reason}")
    return payment
