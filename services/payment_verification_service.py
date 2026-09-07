import os
import re
import io
import json
import hashlib
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageChops, ImageEnhance, ImageStat
from werkzeug.utils import secure_filename
from flask import current_app

from models import db, Payment, PaymentStatus, FraudRisk, EventRegistration, RegistrationStatus

try:
    import pytesseract
    PYTESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None
    PYTESSERACT_AVAILABLE = False


def _configure_tesseract():
    """Detects and configures tesseract binary path if available."""
    if not PYTESSERACT_AVAILABLE:
        return False

    try:
        custom_cmd = current_app.config.get('TESSERACT_CMD') or os.environ.get('TESSERACT_CMD', '')
    except RuntimeError:
        custom_cmd = os.environ.get('TESSERACT_CMD', '')

    if custom_cmd and os.path.exists(custom_cmd):
        pytesseract.pytesseract.tesseract_cmd = custom_cmd
        return True

    import shutil
    if shutil.which('tesseract'):
        return True

    windows_candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\Programs\Tesseract-OCR\tesseract.exe")
    ]
    for candidate in windows_candidates:
        if os.path.exists(candidate):
            pytesseract.pytesseract.tesseract_cmd = candidate
            return True

    return False


def calculate_file_hash(file_path):
    """Computes SHA-256 hash of an uploaded file."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_text_from_screenshot(image_path):
    """
    Extracts text from a payment proof screenshot using OCR.
    Preprocesses with grayscale and contrast enhancement.
    """
    if not PYTESSERACT_AVAILABLE or not _configure_tesseract():
        return ""

    try:
        with Image.open(str(image_path)) as img:
            # Convert to RGB if palette/RGBA
            rgb_img = img.convert('RGB')
            
            # Preprocess image for OCR accuracy
            gray_img = rgb_img.convert('L')
            enhancer = ImageEnhance.Contrast(gray_img)
            enhanced_img = enhancer.enhance(2.0)
            
            text = pytesseract.image_to_string(enhanced_img)
            if not text.strip():
                text = pytesseract.image_to_string(rgb_img)
            return text.strip()
    except Exception as e:
        if current_app:
            current_app.logger.warning(f"Payment proof OCR error: {e}")
        return ""


def parse_payment_details_from_text(raw_text):
    """
    Parses structured payment details from raw OCR text:
    - Detected amount
    - Transaction / UTR ID
    - Receiver UPI ID
    - Receiver Name
    - Date & Time
    - Payment Status
    """
    extracted = {
        'amount': None,
        'transaction_id': None,
        'receiver_upi': None,
        'receiver_name': None,
        'payment_date': None,
        'payment_time': None,
        'payment_status_text': None,
        'raw_text': raw_text
    }

    if not raw_text:
        return extracted

    # 1. Amount Extraction
    # Priority: ₹500, Rs. 500, INR 500, Paid ₹500, Amount: ₹500
    amount_patterns = [
        r'(?:₹|rs\.?|inr)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?)',
        r'(?:paid|amount|total|sent|debited)\s*(?:to|is|:)?\s*(?:₹|rs\.?|inr)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?)',
        r'\b([0-9]{2,6}(?:\.[0-9]{2})?)\s*(?:₹|rs\.?|inr)\b',
    ]

    for pat in amount_patterns:
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            raw_amt_str = match.group(1).replace(',', '')
            try:
                val = float(raw_amt_str)
                if val > 0:
                    extracted['amount'] = val
                    break
            except ValueError:
                pass

    # 2. Transaction ID / UTR extraction
    # Standard UPI UTR: 12-digit number (e.g. 123456789012)
    # UPI Ref No: 123456789012, Txn ID: T24090..., Google Pay / PhonePe format
    txn_patterns = [
        r'(?:upi\s*ref(?:\s*no|\s*id|\s*number)?|utr(?:\s*no)?|rrn)\s*[:\-#.\s]*([0-9]{12})\b',
        r'(?:transaction\s*id|txn\s*id|reference\s*id)\s*[:\-#.\s]*([A-Za-z0-9\-_]{8,35})',
        r'\b([0-9]{12})\b',  # Standalone 12-digit UTR
        r'\b(T[0-9]{18,24})\b',  # PhonePe transaction format
        r'\b(CICAg[A-Za-z0-9_\-]{8,24})\b', # Google Pay format
    ]

    for pat in txn_patterns:
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            extracted['transaction_id'] = match.group(1).strip()
            break

    # 3. UPI ID Extraction
    upi_pattern = r'\b([a-zA-Z0-9.\-_]{2,64}@[a-zA-Z]{2,32})\b'
    upi_match = re.search(upi_pattern, raw_text)
    if upi_match:
        extracted['receiver_upi'] = upi_match.group(1).strip()

    # 4. Receiver Name
    name_patterns = [
        r'(?:paid\s+to|transfer\s+to|sent\s+to|to)\s+([A-Za-z0-9\s.]{3,40}?)(?:\n|,|₹|Rs|UPI|\()',
        r'(?:banking\s+name|merchant\s+name)\s*[:\-]\s*([A-Za-z0-9\s.]{3,40})'
    ]
    for pat in name_patterns:
        match = re.search(pat, raw_text, re.IGNORECASE)
        if match:
            extracted['receiver_name'] = match.group(1).strip()
            break

    # 5. Date & Time
    date_match = re.search(r'\b([0-9]{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+[0-9]{4})\b', raw_text, re.IGNORECASE)
    if not date_match:
        date_match = re.search(r'\b([0-9]{1,2}[/\-.][0-9]{1,2}[/\-.][0-9]{2,4})\b', raw_text)
    if date_match:
        extracted['payment_date'] = date_match.group(1).strip()

    time_match = re.search(r'\b([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?\s*(?:AM|PM|am|pm)?)\b', raw_text)
    if time_match:
        extracted['payment_time'] = time_match.group(1).strip()

    # 6. Payment Status in text
    if re.search(r'(?:payment\s+successful|paid\s+successfully|payment\s+complete|successful|success|completed)', raw_text, re.IGNORECASE):
        extracted['payment_status_text'] = 'SUCCESS'
    elif re.search(r'(?:payment\s+failed|declined|failed)', raw_text, re.IGNORECASE):
        extracted['payment_status_text'] = 'FAILED'
    elif re.search(r'(?:pending|processing)', raw_text, re.IGNORECASE):
        extracted['payment_status_text'] = 'PENDING'

    return extracted


def analyze_image_fraud(image_path, ocr_text="", parsed_details=None):
    """
    Analyzes an uploaded payment proof for signs of manipulation or fraud:
    1. EXIF / metadata software tags (Photoshop, Canva, GIMP, PicsArt, etc.)
    2. Image dimensions & aspect ratio sanity
    3. Compression artifact / Error Level Analysis (ELA)
    4. Structural indicators (missing UPI receipts markers, blank image)
    
    Returns:
    - fraud_risk: 'LOW', 'MEDIUM', or 'HIGH'
    - indicators: list of strings explaining any detected abnormalities
    """
    indicators = []
    suspicious_score = 0  # 0 to 10 scale

    try:
        with Image.open(str(image_path)) as img:
            width, height = img.size
            img_format = img.format

            # Check 1: Dimensions sanity
            if width < 150 or height < 150:
                indicators.append("Image resolution is abnormally low (< 150px), possible thumbnail or icon.")
                suspicious_score += 4

            # Check 2: Metadata / Software Inspection
            info = img.info or {}
            exif_data = img.getexif() if hasattr(img, 'getexif') else {}
            metadata_str = str(info).lower() + " " + str(dict(exif_data)).lower()

            editing_tools = [
                'photoshop', 'canva', 'gimp', 'picsart', 'pixlr',
                'pixelmator', 'inshot', 'photoroom', 'snapseed', 'lightroom'
            ]
            for tool in editing_tools:
                if tool in metadata_str:
                    indicators.append(f"Image metadata indicates editing software was used: '{tool.capitalize()}'.")
                    suspicious_score += 6
                    break

            # Check 3: Error Level Analysis (ELA)
            # Recompress to JPEG at 90% quality and compare pixel difference
            try:
                rgb_img = img.convert('RGB')
                buffer = io.BytesIO()
                rgb_img.save(buffer, 'JPEG', quality=90)
                buffer.seek(0)
                recompressed = Image.open(buffer)

                diff = ImageChops.difference(rgb_img, recompressed)
                stat = ImageStat.Stat(diff)
                mean_diff = sum(stat.mean) / len(stat.mean)
                extrema = [ext[1] for ext in diff.getextrema()]
                max_diff = max(extrema) if extrema else 0

                # High difference spikes or abnormal variance across image
                if max_diff > 160 and mean_diff > 25:
                    indicators.append("Significant compression artifact inconsistency detected (ELA anomaly).")
                    suspicious_score += 3
            except Exception:
                pass

            # Check 4: Content / Structure Inspection
            # Check if image is completely monotone or blank
            try:
                stat = ImageStat.Stat(rgb_img)
                if max(stat.var) < 1.0:
                    indicators.append("Uploaded image appears blank or completely monotone.")
                    suspicious_score += 7
            except Exception:
                pass

    except Exception as e:
        indicators.append(f"Error opening image for manipulation check: {str(e)}")
        suspicious_score += 3

    # Check 5: OCR keyword sanity check
    if ocr_text:
        upi_keywords = ['upi', 'ref', 'utr', 'paid', 'successful', 'success', 'payment', 'transfer', 'rupees', 'bank', 'gpay', 'phonepe', 'paytm']
        matches = [kw for kw in upi_keywords if kw in ocr_text.lower()]
        if len(matches) == 0:
            indicators.append("Receipt does not contain standard UPI/payment terminology.")
            suspicious_score += 3
    else:
        # OCR didn't extract any text
        # If tesseract is configured but image produced 0 text, flag for review
        if PYTESSERACT_AVAILABLE and _configure_tesseract():
            indicators.append("No readable text could be extracted from the screenshot.")
            suspicious_score += 2

    # Calculate final risk tier
    if suspicious_score >= 6:
        fraud_risk = FraudRisk.HIGH
    elif suspicious_score >= 3:
        fraud_risk = FraudRisk.MEDIUM
    else:
        fraud_risk = FraudRisk.LOW

    return fraud_risk, indicators


def check_duplicate_payment(transaction_id=None, screenshot_hash=None, current_payment_id=None):
    """
    Checks if transaction_id or screenshot_hash has already been used in another payment.
    
    Returns:
    - is_duplicate (bool)
    - reason (str or None)
    """
    # 1. Transaction ID check
    if transaction_id and transaction_id.strip():
        clean_txn = transaction_id.strip()
        query = Payment.query.filter(
            Payment.transaction_id == clean_txn,
            Payment.status.in_([PaymentStatus.VERIFIED, PaymentStatus.PENDING, PaymentStatus.MANUAL_REVIEW])
        )
        if current_payment_id:
            query = query.filter(Payment.id != current_payment_id)
        existing_txn = query.first()
        if existing_txn:
            return True, "This transaction has already been used."

    # 2. Screenshot Hash check
    if screenshot_hash and screenshot_hash.strip():
        clean_hash = screenshot_hash.strip()
        query = Payment.query.filter(
            Payment.screenshot_hash == clean_hash,
            Payment.status.in_([PaymentStatus.VERIFIED, PaymentStatus.PENDING, PaymentStatus.MANUAL_REVIEW])
        )
        if current_payment_id:
            query = query.filter(Payment.id != current_payment_id)
        existing_hash = query.first()
        if existing_hash:
            return True, "This payment proof has already been uploaded for another registration."

    return False, None


def verify_payment_submission(registration, entered_transaction_id, uploaded_file):
    """
    Orchestrates complete payment submission and verification pipeline:
    1. Validates event status & eligibility
    2. Saves proof to secure storage
    3. Calculates SHA-256 hash & checks duplicates
    4. Extracts OCR text & parses payment fields
    5. Verifies amount
    6. Verifies transaction ID
    7. Runs image fraud / manipulation detection
    8. Calculates status (PENDING, MANUAL_REVIEW, REJECTED)
    9. Upserts Payment record
    
    Returns:
    - payment (Payment model instance)
    - result_dict: { 'status', 'fraud_risk', 'message', 'reasons': [] }
    """
    event = registration.event
    student = registration.student

    # 1. Validate Event State
    if not event.is_active or event.is_completed:
        return None, {
            'status': PaymentStatus.REJECTED,
            'message': 'Cannot submit payment. This event is completed or no longer active.',
            'reasons': ['Event is completed or inactive.']
        }

    expected_amount = float(event.registration_fee or 0.0)

    # 2. Secure File Ingestion
    filename = secure_filename(f"proof_{registration.id}_{int(datetime.utcnow().timestamp())}_{uploaded_file.filename}")
    upload_dir = Path(current_app.config.get('PAYMENT_PROOF_FOLDER') or (Path(current_app.root_path) / 'static' / 'uploads' / 'payment_proofs'))
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    uploaded_file.save(str(file_path))

    relative_storage_path = f"uploads/payment_proofs/{filename}"
    screenshot_hash = calculate_file_hash(str(file_path))

    # 3. Check for Duplicate Payment / Screenshot
    clean_entered_txn = entered_transaction_id.strip() if entered_transaction_id else ""
    existing_payment = Payment.query.filter_by(registration_id=registration.id).first()
    curr_id = existing_payment.id if existing_payment else None

    is_duplicate, dup_reason = check_duplicate_payment(
        transaction_id=clean_entered_txn,
        screenshot_hash=screenshot_hash,
        current_payment_id=curr_id
    )

    if is_duplicate:
        # Save payment as REJECTED
        payment = _upsert_payment_record(
            registration=registration,
            event=event,
            student=student,
            expected_amount=expected_amount,
            detected_amount=None,
            transaction_id=clean_entered_txn,
            screenshot_path=relative_storage_path,
            screenshot_hash=screenshot_hash,
            status=PaymentStatus.REJECTED,
            fraud_risk=FraudRisk.HIGH,
            fraud_details=json.dumps([dup_reason]),
            ocr_data="{}",
            verification_reason=dup_reason
        )
        return payment, {
            'status': PaymentStatus.REJECTED,
            'fraud_risk': FraudRisk.HIGH,
            'message': dup_reason,
            'reasons': [dup_reason]
        }

    # 4. OCR Extraction & Parsing
    ocr_raw_text = extract_text_from_screenshot(str(file_path))
    parsed = parse_payment_details_from_text(ocr_raw_text)
    detected_amount = parsed.get('amount')
    extracted_txn_id = parsed.get('transaction_id')

    # 5. Amount Verification
    reasons = []
    is_amount_mismatch = False
    if detected_amount is not None:
        # Compare within 1 rupee tolerance for formatting/rounding
        if abs(detected_amount - expected_amount) > 1.0:
            is_amount_mismatch = True
            reasons.append("Payment verification failed because the uploaded payment amount does not match the event registration fee.")

    # 6. Transaction ID Verification
    is_txn_mismatch = False
    if clean_entered_txn and extracted_txn_id:
        # Compare normalized alphanumeric characters
        norm_entered = re.sub(r'[^A-Za-z0-9]', '', clean_entered_txn).upper()
        norm_extracted = re.sub(r'[^A-Za-z0-9]', '', extracted_txn_id).upper()
        if norm_entered != norm_extracted and (norm_entered not in norm_extracted and norm_extracted not in norm_entered):
            is_txn_mismatch = True
            reasons.append("Transaction ID does not match the uploaded payment proof.")

    # 7. Fraud & Manipulation Detection
    fraud_risk, fraud_indicators = analyze_image_fraud(str(file_path), ocr_text=ocr_raw_text, parsed_details=parsed)

    # 8. Calculate Status
    if is_amount_mismatch or is_txn_mismatch:
        final_status = PaymentStatus.REJECTED
        verif_reason = "; ".join(reasons)
    elif fraud_risk in (FraudRisk.HIGH, FraudRisk.MEDIUM):
        final_status = PaymentStatus.MANUAL_REVIEW
        verif_reason = f"Flagged for manual review due to {fraud_risk} risk indicators: {', '.join(fraud_indicators)}"
    else:
        final_status = PaymentStatus.PENDING
        verif_reason = "Automated verification checks passed (Amount & Transaction ID valid). Awaiting organizer review."

    # 9. Upsert Payment Record
    payment = _upsert_payment_record(
        registration=registration,
        event=event,
        student=student,
        expected_amount=expected_amount,
        detected_amount=detected_amount,
        transaction_id=clean_entered_txn,
        screenshot_path=relative_storage_path,
        screenshot_hash=screenshot_hash,
        status=final_status,
        fraud_risk=fraud_risk,
        fraud_details=json.dumps(fraud_indicators),
        ocr_data=json.dumps(parsed),
        verification_reason=verif_reason
    )

    return payment, {
        'status': final_status,
        'fraud_risk': fraud_risk,
        'message': verif_reason,
        'reasons': reasons or fraud_indicators
    }


def _upsert_payment_record(registration, event, student, expected_amount, detected_amount,
                           transaction_id, screenshot_path, screenshot_hash, status,
                           fraud_risk, fraud_details, ocr_data, verification_reason):
    """Helper to persist or update a Payment record."""
    payment = Payment.query.filter_by(registration_id=registration.id).first()
    if not payment:
        payment = Payment(
            registration_id=registration.id,
            event_id=event.id,
            student_id=student.id,
            organizer_id=event.organizer_id,
            amount=expected_amount,
            currency='INR',
            expected_amount=expected_amount,
            detected_amount=detected_amount,
            transaction_id=transaction_id,
            payment_method='UPI_DIRECT',
            payment_screenshot=screenshot_path,
            screenshot_hash=screenshot_hash,
            status=status,
            fraud_risk=fraud_risk,
            fraud_details=fraud_details,
            ocr_extracted_data=ocr_data,
            verification_reason=verification_reason,
            submitted_at=datetime.utcnow()
        )
        db.session.add(payment)
    else:
        payment.event_id = event.id
        payment.student_id = student.id
        payment.organizer_id = event.organizer_id
        payment.amount = expected_amount
        payment.expected_amount = expected_amount
        payment.detected_amount = detected_amount
        payment.transaction_id = transaction_id
        payment.payment_screenshot = screenshot_path
        payment.screenshot_hash = screenshot_hash
        payment.status = status
        payment.fraud_risk = fraud_risk
        payment.fraud_details = fraud_details
        payment.ocr_extracted_data = ocr_data
        payment.verification_reason = verification_reason
        payment.submitted_at = datetime.utcnow()

    db.session.commit()
    return payment
