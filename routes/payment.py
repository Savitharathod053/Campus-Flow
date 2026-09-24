import os
from datetime import datetime
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, abort, send_file
from models import db, EventRegistration, RegistrationStatus, Payment, PaymentStatus, FraudRisk, UserRole
from routes.auth import login_required, get_current_user
from services.payment_verification_service import verify_payment_submission

payment_bp = Blueprint('payment', __name__, url_prefix='/payment')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@payment_bp.route('/checkout/<int:registration_id>')
@login_required
def checkout(registration_id):
    user = get_current_user()
    registration = EventRegistration.query.get_or_404(registration_id)

    if registration.student_id != user.id and not user.is_admin:
        abort(403)

    if registration.is_confirmed:
        flash('This registration is already confirmed.', 'info')
        return redirect(url_for('student.ticket', code=registration.registration_code))

    event = registration.event

    # Free event check
    if event.is_free or (event.registration_fee or 0) <= 0:
        registration.status = RegistrationStatus.CONFIRMED
        from services.qr_service import generate_ticket_qr
        if not registration.qr_code_image:
            registration.qr_code_image = generate_ticket_qr(registration.registration_code)
        db.session.commit()
        flash('Event is free. Registration confirmed!', 'success')
        return redirect(url_for('student.ticket', code=registration.registration_code))

    # Event active check
    if not event.is_active or event.is_completed:
        flash('This event is completed or no longer accepting payments.', 'danger')
        return redirect(url_for('student.my_events'))

    # Existing payment record if already submitted
    payment = Payment.query.filter_by(registration_id=registration.id).first()

    return render_template(
        'student/checkout.html',
        registration=registration,
        event=event,
        user=user,
        payment=payment,
        amount=event.registration_fee
    )


@payment_bp.route('/submit-proof/<int:registration_id>', methods=['POST'])
@login_required
def submit_proof(registration_id):
    user = get_current_user()
    registration = EventRegistration.query.get_or_404(registration_id)

    if registration.student_id != user.id and not user.is_admin:
        abort(403)

    if registration.is_confirmed:
        flash('This registration is already confirmed.', 'info')
        return redirect(url_for('student.ticket', code=registration.registration_code))

    event = registration.event

    # 1. Event Validation
    if not event.is_active or event.is_completed:
        flash('Cannot submit payment. This event is completed or no longer active.', 'danger')
        return redirect(url_for('student.my_events'))

    # 2. Extract and sanitize inputs (DO NOT trust amount from form)
    transaction_id = request.form.get('transaction_id', '').strip()
    if not transaction_id:
        flash('Transaction/Reference ID is required. Please enter the UTR or reference number.', 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    if 'payment_screenshot' not in request.files:
        flash('Please upload your payment screenshot proof.', 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    file = request.files['payment_screenshot']
    if not file or not file.filename:
        flash('No payment screenshot selected. Please choose an image file.', 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    if not allowed_file(file.filename):
        flash('Invalid image format! Only PNG, JPG, JPEG, and WEBP files are allowed.', 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    # MIME type check
    content_type = getattr(file, 'content_type', '') or getattr(file, 'mimetype', '')
    allowed_mimes = {'image/png', 'image/jpeg', 'image/jpg', 'image/pjpeg', 'image/webp'}
    if content_type and content_type.lower() not in allowed_mimes:
        flash('Invalid image MIME type! Only standard PNG, JPEG, and WEBP images are accepted.', 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    # Check file size (10 MB limit)
    file.seek(0, os.SEEK_END)
    size_bytes = file.tell()
    file.seek(0)
    max_size = current_app.config.get('MAX_PAYMENT_PROOF_SIZE', 10 * 1024 * 1024)
    if size_bytes > max_size:
        flash(f'File size exceeds {max_size // (1024 * 1024)}MB limit. Please upload a smaller image.', 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    # 3. Run verification pipeline: duplicate check, OCR, amount match, AI vision fraud analysis
    payment, result = verify_payment_submission(
        registration=registration,
        entered_transaction_id=transaction_id,
        uploaded_file=file
    )

    if not payment:
        flash(result.get('message', 'Failed to process payment submission.'), 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))

    # 4. Handle Status
    # IMPORTANT: Ticket is NEVER generated here. Ticket is ONLY generated upon organizer VERIFIED.
    status = payment.status
    if status == PaymentStatus.PAYMENT_VERIFICATION_FAILED:
        flash("Transaction ID does not match the payment screenshot. Please check your Transaction ID and upload the correct payment screenshot.", 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))
    elif status == PaymentStatus.REJECTED:
        flash(f"Payment verification failed: {payment.verification_reason}", 'danger')
        return redirect(url_for('payment.checkout', registration_id=registration.id))
    elif status in (PaymentStatus.TRANSACTION_ID_VERIFIED, PaymentStatus.MANUAL_REVIEW, PaymentStatus.PENDING):
        # Dispatch in-app notifications and emails to organizer and student
        try:
            from services.notification_service import create_notification
            from models.notification import NotificationType
            from services.email_service import send_payment_proof_submitted_email

            event_obj = registration.event
            organizer_obj = event_obj.organizer if event_obj else None

            # 1. Notify Organizer
            if organizer_obj:
                msg_text = f"Student {user.name} submitted payment proof of ₹{payment.amount:.2f} for '{event_obj.title}' (Txn: {payment.transaction_id}). Status: {payment.status_label}."
                create_notification(
                    user_id=organizer_obj.id,
                    title=f"Payment Verification: {user.name}",
                    message=msg_text,
                    notification_type=NotificationType.SYSTEM,
                    link=url_for('organizer.payment_verification', event_id=event_obj.id)
                )

            # 2. Notify Student (never expose internal fraud details)
            create_notification(
                user_id=user.id,
                title=f"Payment Proof Submitted: {event_obj.title}",
                message=f"Your payment proof for '{event_obj.title}' has been submitted and is under verification. Ticket will be activated once verified.",
                notification_type=NotificationType.SYSTEM,
                link=url_for('student.my_events')
            )

            # 3. Email both parties
            send_payment_proof_submitted_email(payment, user, event_obj, organizer_obj)
        except Exception as exc:
            current_app.logger.warning(f"Could not dispatch payment submission notifications: {exc}")

        # Requirement 7: Show student friendly "under verification" message without internal scores
        flash("Your payment proof has been submitted and is under verification.", 'info')
        return redirect(url_for('student.my_events'))
    else:
        return redirect(url_for('student.my_events'))


@payment_bp.route('/proof/<int:payment_id>')
@login_required
def view_proof(payment_id):
    """
    Securely serves the payment screenshot proof.
    Authorization: Only the student who submitted it, the organizer of the event, or an admin can access.
    """
    user = get_current_user()
    payment = Payment.query.get_or_404(payment_id)

    # Authorization check
    is_owner_student = (payment.student_id == user.id) or (payment.registration and payment.registration.student_id == user.id)
    is_event_organizer = (payment.organizer_id == user.id) or (payment.event and payment.event.organizer_id == user.id)
    is_authorized = is_owner_student or is_event_organizer or user.is_admin

    if not is_authorized:
        abort(403)

    if not payment.payment_screenshot:
        abort(404)

    full_path = Path(current_app.root_path) / 'static' / payment.payment_screenshot
    if not full_path.exists():
        # Check relative to base folder
        full_path = Path(current_app.config.get('PAYMENT_PROOF_FOLDER', '')) / Path(payment.payment_screenshot).name
        if not full_path.exists():
            abort(404)

    ext = full_path.suffix.lower()
    mimetype = 'image/png'
    if ext in ('.jpg', '.jpeg'):
        mimetype = 'image/jpeg'
    elif ext == '.webp':
        mimetype = 'image/webp'

    return send_file(str(full_path), mimetype=mimetype, as_attachment=False)


# ==============================================================================
# RAZORPAY PAYMENT GATEWAY ENDPOINTS (TEST & LIVE MODES)
# ==============================================================================

@payment_bp.route('/razorpay/create-order/<int:registration_id>', methods=['POST'])
@login_required
def razorpay_create_order(registration_id):
    """
    Creates a unique Razorpay payment order for the specified registration.
    Returns the order ID and key ID for client-side modal checkout.
    """
    user = get_current_user()
    registration = EventRegistration.query.get_or_404(registration_id)

    if registration.student_id != user.id and not user.is_admin:
        abort(403)

    if registration.is_confirmed:
        return jsonify({
            'success': False,
            'message': 'This registration is already confirmed.',
            'redirect_url': url_for('student.ticket', code=registration.registration_code)
        }), 400

    event = registration.event
    if not event.is_active or event.is_completed:
        return jsonify({
            'success': False,
            'message': 'This event is completed or no longer accepting payments.'
        }), 400

    from services.razorpay_service import create_razorpay_order
    try:
        order_info = create_razorpay_order(registration)
        return jsonify({
            'success': True,
            'order': order_info
        })
    except Exception as exc:
        current_app.logger.error(f"Failed to generate Razorpay order for reg {registration_id}: {exc}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f"Unable to create Razorpay payment order: {str(exc)}"
        }), 500


@payment_bp.route('/razorpay/verify', methods=['POST'])
@login_required
def razorpay_verify_payment():
    """
    Verifies Razorpay payment signature from client-side checkout callback.
    Once verified, automatically marks payment VERIFIED, confirms registration,
    and generates the entry ticket QR code.
    """
    user = get_current_user()
    data = request.get_json(silent=True) or request.form.to_dict()

    razorpay_order_id = (data.get('razorpay_order_id') or '').strip()
    razorpay_payment_id = (data.get('razorpay_payment_id') or '').strip()
    razorpay_signature = (data.get('razorpay_signature') or '').strip()

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return jsonify({
            'success': False,
            'message': 'Incomplete Razorpay payment verification details.'
        }), 400

    from services.razorpay_service import verify_payment_signature, process_successful_payment

    # 1. Cryptographic HMAC-SHA256 signature verification
    if not verify_payment_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
        current_app.logger.warning(
            f"Razorpay payment signature mismatch for order: {razorpay_order_id}, payment: {razorpay_payment_id}"
        )
        return jsonify({
            'success': False,
            'message': 'Security validation failed: Invalid payment signature.'
        }), 400

    # 2. Reconcile transaction and confirm registration idempotently
    payment, ok, msg = process_successful_payment(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature
    )

    if not ok or not payment:
        return jsonify({
            'success': False,
            'message': msg or 'Payment processing failed.'
        }), 400

    registration = payment.registration
    reg_code = registration.registration_code if registration else ''

    flash('Payment successfully verified via Razorpay! Your entry ticket and QR pass are ready.', 'success')
    return jsonify({
        'success': True,
        'message': 'Payment successfully verified.',
        'redirect_url': url_for('student.ticket', code=reg_code) if reg_code else url_for('student.my_events')
    })


def handle_razorpay_webhook():
    """
    Processes asynchronous Razorpay webhook events idempotently.
    Supports events: payment.captured, order.paid, payment.failed.
    """
    raw_body = request.get_data()
    signature = request.headers.get('X-Razorpay-Signature', '').strip()

    from services.razorpay_service import (
        verify_webhook_signature,
        process_successful_payment,
        process_failed_payment
    )

    if not verify_webhook_signature(raw_body, signature):
        current_app.logger.warning("Rejected Razorpay webhook with invalid signature")
        return jsonify({'status': 'error', 'message': 'Invalid signature'}), 400

    event_data = request.get_json(silent=True) or {}
    event_type = event_data.get('event')
    event_id = event_data.get('id')
    payload = event_data.get('payload', {})

    payment_entity = payload.get('payment', {}).get('entity', {})
    order_entity = payload.get('order', {}).get('entity', {})

    razorpay_payment_id = payment_entity.get('id')
    razorpay_order_id = payment_entity.get('order_id') or order_entity.get('id')

    current_app.logger.info(f"Received Razorpay webhook: {event_type}, ID: {event_id}, Order: {razorpay_order_id}")

    if event_type in ('payment.captured', 'order.paid'):
        process_successful_payment(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            webhook_event_id=event_id
        )
    elif event_type in ('payment.failed',):
        error_desc = payment_entity.get('error_description') or 'Payment failed on Razorpay'
        process_failed_payment(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            failure_reason=error_desc,
            webhook_event_id=event_id
        )

    return jsonify({'status': 'ok'}), 200


@payment_bp.route('/webhook/razorpay', methods=['POST'])
def razorpay_webhook():
    return handle_razorpay_webhook()


