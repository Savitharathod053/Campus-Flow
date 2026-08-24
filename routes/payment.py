from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, abort
from models import db, EventRegistration, RegistrationStatus, Payment, PaymentStatus, UserRole
from routes.auth import login_required, get_current_user
from services.razorpay_service import create_razorpay_order, verify_razorpay_signature

payment_bp = Blueprint('payment', __name__, url_prefix='/payment')

@payment_bp.route('/checkout/<int:registration_id>')
@login_required
def checkout(registration_id):
    user = get_current_user()
    registration = EventRegistration.query.get_or_404(registration_id)

    if registration.student_id != user.id:
        abort(403)

    if registration.is_confirmed:
        flash('This registration is already confirmed and paid.', 'info')
        return redirect(url_for('student.ticket', code=registration.registration_code))

    event = registration.event
    amount = event.registration_fee

    if amount <= 0:
        registration.status = RegistrationStatus.CONFIRMED
        db.session.commit()
        flash('Event is free. Registration confirmed!', 'success')
        return redirect(url_for('student.ticket', code=registration.registration_code))

    # Create official Razorpay Order
    order_data = create_razorpay_order(
        amount_in_rupees=amount,
        receipt_id=f"rec_{registration.id}",
        notes={
            'event_id': str(event.id),
            'student_id': str(user.id),
            'registration_code': registration.registration_code
        }
    )

    # Upsert Payment record with pending status
    payment = Payment.query.filter_by(registration_id=registration.id).first()
    if not payment:
        payment = Payment(
            registration_id=registration.id,
            amount=amount,
            currency='INR',
            razorpay_order_id=order_data['order_id'],
            status=PaymentStatus.PENDING
        )
        db.session.add(payment)
    else:
        payment.razorpay_order_id = order_data['order_id']
        payment.amount = amount
    db.session.commit()

    return render_template(
        'student/checkout.html',
        registration=registration,
        event=event,
        user=user,
        order_data=order_data
    )


@payment_bp.route('/simulate/<int:registration_id>', methods=['POST'])
@login_required
def simulate_payment(registration_id):
    """
    Instant test payment simulation for sandbox evaluation without real credit cards.
    """
    user = get_current_user()
    registration = EventRegistration.query.get_or_404(registration_id)

    if registration.student_id != user.id:
        abort(403)

    if registration.is_confirmed:
        flash('This registration is already confirmed and paid.', 'info')
        return redirect(url_for('student.ticket', code=registration.registration_code))

    import uuid
    sim_order_id = f"order_sim_{registration.id}_{uuid.uuid4().hex[:6]}"
    sim_pay_id = f"pay_sim_{uuid.uuid4().hex[:10]}"

    payment = Payment.query.filter_by(registration_id=registration.id).first()
    if not payment:
        payment = Payment(
            registration_id=registration.id,
            amount=registration.event.registration_fee,
            currency='INR',
            razorpay_order_id=sim_order_id
        )
        db.session.add(payment)

    payment.razorpay_order_id = sim_order_id
    payment.razorpay_payment_id = sim_pay_id
    payment.razorpay_signature = 'SIMULATED_TEST_SIGNATURE'
    payment.status = PaymentStatus.SUCCESS
    payment.payment_method = 'SANDBOX_SIMULATED'

    # Generate ticket QR code upon confirmed payment
    from services.qr_service import generate_ticket_qr
    if not registration.qr_code_image:
        registration.qr_code_image = generate_ticket_qr(registration.registration_code)

    registration.status = RegistrationStatus.CONFIRMED
    db.session.commit()

    flash('Payment completed successfully! Your event ticket and QR pass have been generated.', 'success')
    return redirect(url_for('student.ticket', code=registration.registration_code))


@payment_bp.route('/verify', methods=['POST'])
@login_required
def verify_payment():
    user = get_current_user()
    
    razorpay_order_id = request.form.get('razorpay_order_id', '').strip()
    razorpay_payment_id = request.form.get('razorpay_payment_id', '').strip()
    razorpay_signature = request.form.get('razorpay_signature', '').strip()
    registration_id = request.form.get('registration_id')

    if not registration_id:
        flash('Invalid payment response. Missing registration identifier.', 'danger')
        return redirect(url_for('student.my_events'))

    registration = EventRegistration.query.get_or_404(int(registration_id))

    if registration.student_id != user.id:
        abort(403)

    # Check if sandbox simulation bypass was submitted
    is_simulation = (
        current_app.config.get('RAZORPAY_SANDBOX_SIMULATION', False) and
        (razorpay_signature == 'SIMULATED_TEST_SIGNATURE' or 
         razorpay_payment_id.startswith('pay_sim_') or 
         razorpay_order_id.startswith('order_sim_') or
         razorpay_order_id.startswith('order_dev_'))
    )

    if not is_simulation:
        # Verify signature using Razorpay HMAC-SHA256 signature
        is_valid = verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature)
        if not is_valid:
            flash('Payment verification failed! Invalid or tampered payment signature.', 'danger')
            return redirect(url_for('payment.checkout', registration_id=registration.id))

    # Update payment record to SUCCESS
    payment = Payment.query.filter_by(registration_id=registration.id).first()
    if not payment:
        payment = Payment(
            registration_id=registration.id,
            amount=registration.event.registration_fee,
            currency='INR',
            razorpay_order_id=razorpay_order_id
        )
        db.session.add(payment)

    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = razorpay_signature
    payment.status = PaymentStatus.SUCCESS
    payment.payment_method = 'SANDBOX_SIMULATED' if is_simulation else 'RAZORPAY_CHECKOUT'
    
    # Generate ticket QR code upon confirmed payment
    from services.qr_service import generate_ticket_qr
    if not registration.qr_code_image:
        registration.qr_code_image = generate_ticket_qr(registration.registration_code)

    # Confirm registration and seat
    registration.status = RegistrationStatus.CONFIRMED
    db.session.commit()

    flash('Payment verified successfully! Your event ticket and QR pass have been generated.', 'success')
    return redirect(url_for('student.ticket', code=registration.registration_code))
