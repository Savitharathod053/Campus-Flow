import hmac
import hashlib
from flask import current_app
import razorpay

def get_razorpay_client():
    """
    Initialize and return official Razorpay Client instance with configured keys.
    """
    key_id = current_app.config.get('RAZORPAY_KEY_ID')
    key_secret = current_app.config.get('RAZORPAY_KEY_SECRET')
    if key_id and key_secret:
        return razorpay.Client(auth=(key_id, key_secret))
    return None


def create_razorpay_order(amount_in_rupees, receipt_id, notes=None):
    """
    Creates an official Razorpay Order for checkout.
    Razorpay expects amount in paise (1 INR = 100 paise).
    """
    amount_in_paise = int(amount_in_rupees * 100)
    client = get_razorpay_client()
    key_id = current_app.config.get('RAZORPAY_KEY_ID', '')

    if client:
        try:
            order_data = {
                'amount': amount_in_paise,
                'currency': 'INR',
                'receipt': str(receipt_id),
                'notes': notes or {},
                'payment_capture': 1
            }
            order = client.order.create(data=order_data)
            return {
                'order_id': order['id'],
                'amount': amount_in_rupees,
                'amount_paise': amount_in_paise,
                'currency': 'INR',
                'key_id': key_id
            }
        except Exception as e:
            current_app.logger.error(f"Razorpay order creation error: {e}")

    # Fallback order descriptor for development / test keys
    return {
        'order_id': f"order_dev_{receipt_id}",
        'amount': amount_in_rupees,
        'amount_paise': amount_in_paise,
        'currency': 'INR',
        'key_id': key_id
    }


def verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """
    Verifies the cryptographic HMAC-SHA256 signature returned by Razorpay Checkout.
    """
    client = get_razorpay_client()
    key_secret = current_app.config.get('RAZORPAY_KEY_SECRET', '')

    if client and key_secret:
        try:
            params_dict = {
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature
            }
            client.utility.verify_payment_signature(params_dict)
            return True
        except Exception as e:
            current_app.logger.warning(f"Razorpay signature verification failed via SDK: {e}")

    # Cryptographic HMAC-SHA256 verification
    if key_secret and razorpay_signature:
        generated_signature = hmac.new(
            key_secret.encode('utf-8'),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(generated_signature, razorpay_signature)

    return False
