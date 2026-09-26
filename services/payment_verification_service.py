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
from fraud_detection import check_payment_image, FraudStatus

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

    candidate_txns = []
    for pat in txn_patterns:
        for m in re.finditer(pat, raw_text, re.IGNORECASE):
            cand = m.group(1).strip()
            if cand and cand not in candidate_txns:
                candidate_txns.append(cand)

    extracted['transaction_id'] = candidate_txns[0] if candidate_txns else None
    extracted['candidate_transaction_ids'] = candidate_txns

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


def normalize_transaction_id(val):
    """
    Normalizes a transaction ID or reference number:
    - Converts to uppercase.
    - Strips whitespace, hyphens, colons, dots, slashes, and symbols.
    """
    if not val:
        return ""
    return re.sub(r'[\s\-_.:#/]+', '', str(val)).upper()


def check_duplicate_event_transaction(event_id, transaction_id, current_payment_id=None, current_registration_id=None):
    """
    Prevents the same Transaction ID from being used by multiple students for the same event.
    Returns (is_duplicate: bool, reason: str or None)
    """
    norm_txn = normalize_transaction_id(transaction_id)
    if not norm_txn or len(norm_txn) < 6:
        return False, None

    query = Payment.query.filter(Payment.event_id == event_id)
    if current_payment_id:
        query = query.filter(Payment.id != current_payment_id)
    if current_registration_id:
        query = query.filter(Payment.registration_id != current_registration_id)

    existing_event_payments = query.all()
    for p in existing_event_payments:
        p_norm = normalize_transaction_id(p.transaction_id)
        if p_norm and p_norm == norm_txn:
            return True, f"Duplicate Transaction ID detected for this event: Another participant already submitted Transaction ID '{transaction_id}'."

    return False, None


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

            editing_software = [
                'photoshop', 'gimp', 'canva', 'picsart', 'pixlr', 'lightroom',
                'snapseed', 'affinity', 'coreldraw', 'paint.net', 'sketch'
            ]
            found_software = [s for s in editing_software if s in metadata_str]
            if found_software:
                software_name = found_software[0].title()
                indicators.append(f"Image was modified using photo-editing software: {software_name}")
                suspicious_score += 7

            # Check 3: Aspect Ratio Check
            aspect_ratio = height / float(width)
            if aspect_ratio < 0.3 or aspect_ratio > 3.5:
                indicators.append(f"Unusual image aspect ratio ({aspect_ratio:.2f}) for a mobile receipt.")
                suspicious_score += 2

            # Check 4: Error Level Analysis (ELA)
            try:
                temp_ela_path = str(image_path) + ".ela.jpg"
                img.save(temp_ela_path, 'JPEG', quality=90)
                with Image.open(temp_ela_path) as resaved_img:
                    diff = ImageChops.difference(img.convert('RGB'), resaved_img.convert('RGB'))
                    stat = ImageStat.Stat(diff)
                    diff_mean = sum(stat.mean) / len(stat.mean)
                    if diff_mean > 35.0:
                        indicators.append("Significant compression inconsistency detected (Error Level Analysis anomaly).")
                        suspicious_score += 4
                if os.path.exists(temp_ela_path):
                    os.remove(temp_ela_path)
            except Exception:
                pass

    except Exception as e:
        indicators.append(f"Image analysis warning: {str(e)}")
        suspicious_score += 2

    # Check 5: OCR Content Checks
    if ocr_text:
        text_lower = ocr_text.lower()
        upi_markers = ['upi', 'ref', 'utr', 'paid', 'successful', 'rupees', 'gpay', 'phonepe', 'paytm', 'bhim', 'bank']
        has_upi_marker = any(marker in text_lower for marker in upi_markers)
        if not has_upi_marker and len(ocr_text.strip()) > 30:
            indicators.append("Screenshot text does not contain common UPI receipt keywords (UPI, UTR, Paid, Bank).")
            suspicious_score += 3

    if suspicious_score >= 6:
        fraud_risk = FraudRisk.HIGH
    elif suspicious_score >= 3:
        fraud_risk = FraudRisk.MEDIUM
    else:
        fraud_risk = FraudRisk.LOW

    return fraud_risk, indicators


def check_duplicate_payment(transaction_id, screenshot_hash, current_payment_id=None):
    """
    Checks if this transaction ID or screenshot has already been used for another payment.
    """
    # 1. Transaction ID check (exact and normalized match)
    if transaction_id and transaction_id.strip():
        clean_txn = transaction_id.strip()
        norm_txn = normalize_transaction_id(clean_txn)
        query = Payment.query.filter(
            Payment.status.in_([
                PaymentStatus.VERIFIED,
                PaymentStatus.PENDING,
                PaymentStatus.MANUAL_REVIEW,
                PaymentStatus.TRANSACTION_ID_VERIFIED
            ])
        )
        if current_payment_id:
            query = query.filter(Payment.id != current_payment_id)
        
        existing_txns = query.all()
        for p in existing_txns:
            if p.transaction_id:
                if p.transaction_id.strip() == clean_txn:
                    return True, "This transaction has already been used."
                if norm_txn and len(norm_txn) >= 6 and normalize_transaction_id(p.transaction_id) == norm_txn:
                    return True, "This transaction has already been used."
            if p.extracted_transaction_id:
                if norm_txn and len(norm_txn) >= 6 and normalize_transaction_id(p.extracted_transaction_id) == norm_txn:
                    return True, "This transaction has already been used."

    # 2. Screenshot Hash check
    if screenshot_hash and screenshot_hash.strip():
        clean_hash = screenshot_hash.strip()
        query = Payment.query.filter(
            Payment.screenshot_hash == clean_hash,
            Payment.status.in_([
                PaymentStatus.VERIFIED,
                PaymentStatus.PENDING,
                PaymentStatus.MANUAL_REVIEW,
                PaymentStatus.TRANSACTION_ID_VERIFIED
            ])
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
    6. Verifies transaction ID (Normalized OCR comparison)
    7. Runs image fraud / manipulation detection
    8. Calculates status (TRANSACTION_ID_VERIFIED, PAYMENT_VERIFICATION_FAILED, PENDING, REJECTED)
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

    # 2. Secure File Ingestion & Persistent Storage
    from services.storage_service import upload_file, sanitize_storage_filename

    upload_dir = Path(current_app.config.get('PAYMENT_PROOF_FOLDER') or (Path(current_app.root_path) / 'static' / 'uploads' / 'payment_proofs'))
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    local_temp_name = sanitize_storage_filename(uploaded_file.filename, prefix=f"proof_{registration.id}")
    file_path = upload_dir / local_temp_name
    uploaded_file.save(str(file_path))

    screenshot_hash = calculate_file_hash(str(file_path))

    # Upload to persistent storage (Supabase in production, local fallback in dev)
    success, public_url, storage_err = upload_file(
        str(file_path),
        folder='payment_proofs',
        filename=uploaded_file.filename,
        prefix=f"proof_{registration.id}"
    )
    if not success:
        current_app.logger.error(f"Failed to upload payment proof to storage: {storage_err}")
        return None, {
            'status': PaymentStatus.REJECTED,
            'fraud_risk': FraudRisk.HIGH,
            'message': 'Failed to save payment proof to cloud storage. Please try again.',
            'reasons': [f"Storage error: {storage_err}"]
        }

    relative_storage_path = public_url

    # 3. Check for Global Duplicate Payment / Screenshot
    clean_entered_txn = entered_transaction_id.strip() if entered_transaction_id else ""
    norm_entered = normalize_transaction_id(clean_entered_txn)
    existing_payment = Payment.query.filter_by(registration_id=registration.id).first()
    curr_id = existing_payment.id if existing_payment else None

    is_duplicate, dup_reason = check_duplicate_payment(
        transaction_id=clean_entered_txn,
        screenshot_hash=screenshot_hash,
        current_payment_id=curr_id
    )

    if is_duplicate:
        payment = _upsert_payment_record(
            registration=registration,
            event=event,
            student=student,
            expected_amount=expected_amount,
            detected_amount=None,
            transaction_id=clean_entered_txn,
            extracted_transaction_id=None,
            screenshot_path=relative_storage_path,
            screenshot_hash=screenshot_hash,
            status=PaymentStatus.REJECTED,
            fraud_risk=FraudRisk.HIGH,
            fraud_details=json.dumps([dup_reason]),
            ocr_data="{}",
            verification_reason=dup_reason,
            fraud_status=FraudStatus.SUSPICIOUS,
            fraud_score=1.0,
            fraud_label="DUPLICATE_PAYMENT",
            fraud_model="DUPLICATE_RULE",
            fraud_checked_at=datetime.utcnow()
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
    candidate_txns = parsed.get('candidate_transaction_ids', [])
    norm_extracted = normalize_transaction_id(extracted_txn_id) if extracted_txn_id else ""
    norm_ocr_text = normalize_transaction_id(ocr_raw_text)

    # 5. Amount Verification
    reasons = []
    is_amount_mismatch = False
    if detected_amount is not None:
        # Compare within 1 rupee tolerance for formatting/rounding
        if abs(detected_amount - expected_amount) > 1.0:
            is_amount_mismatch = True
            reasons.append("Payment verification failed because the uploaded payment amount does not match the event registration fee.")

    # 6. Automatic Transaction ID Verification (Normalized Comparison)
    cand_norms = [normalize_transaction_id(c) for c in candidate_txns]
    is_txn_match = False
    if norm_entered:
        if norm_extracted and norm_entered == norm_extracted:
            is_txn_match = True
        elif norm_entered in cand_norms:
            is_txn_match = True
        elif len(norm_entered) >= 6 and norm_entered in norm_ocr_text:
            is_txn_match = True

    # Check for duplicate Transaction ID within the same event
    is_event_dup, event_dup_reason = check_duplicate_event_transaction(
        event_id=event.id,
        transaction_id=clean_entered_txn,
        current_payment_id=curr_id,
        current_registration_id=registration.id
    )

    # 7. AI Vision & Heuristic Fraud & Manipulation Detection
    ai_fraud_result = check_payment_image(str(file_path))
    heuristic_risk, heuristic_indicators = analyze_image_fraud(str(file_path), ocr_text=ocr_raw_text, parsed_details=parsed)

    fraud_indicators = list(heuristic_indicators)
    ai_status = ai_fraud_result.get('fraud_status', FraudStatus.LOW_RISK)
    ai_conf = float(ai_fraud_result.get('confidence', 0.0))
    ai_model = str(ai_fraud_result.get('model', 'HuggingFace'))
    ai_label = str(ai_fraud_result.get('label', ''))
    ai_reason = str(ai_fraud_result.get('reason', ''))

    if ai_reason:
        fraud_indicators.append(f"AI Model ({ai_model}): {ai_reason}")

    # Determine composite fraud_status and fraud_risk
    if is_event_dup:
        fraud_risk = FraudRisk.HIGH
        fraud_status = FraudStatus.SUSPICIOUS
        fraud_indicators.append(event_dup_reason)
    elif ai_status == FraudStatus.SUSPICIOUS or heuristic_risk == FraudRisk.HIGH:
        fraud_risk = FraudRisk.HIGH
        fraud_status = FraudStatus.SUSPICIOUS
    elif ai_status == FraudStatus.MANUAL_REVIEW or heuristic_risk == FraudRisk.MEDIUM:
        fraud_risk = FraudRisk.MEDIUM
        fraud_status = FraudStatus.MANUAL_REVIEW
    else:
        fraud_risk = FraudRisk.LOW
        fraud_status = FraudStatus.LOW_RISK

    # 8. Calculate Final Payment Status according to Verification Rules:
    # IMPORTANT: The system must NOT approve or reject a payment only because of the Hugging Face image model.
    # The image model is only an advisory risk signal.
    if ocr_raw_text and not is_txn_match:
        # Mismatch detected by OCR
        final_status = PaymentStatus.PAYMENT_VERIFICATION_FAILED
        verif_reason = "Transaction ID does not match the payment screenshot. Please check your Transaction ID and upload the correct payment screenshot."
        reasons.append(verif_reason)
    elif is_amount_mismatch:
        final_status = PaymentStatus.REJECTED
        verif_reason = "; ".join(reasons)
    elif is_txn_match:
        # Manually entered Transaction ID matches Transaction ID in uploaded screenshot
        if is_event_dup:
            final_status = PaymentStatus.MANUAL_REVIEW
            verif_reason = f"Transaction ID verified against screenshot, but {event_dup_reason} Flagged for organizer review."
        elif fraud_status in (FraudStatus.SUSPICIOUS, FraudStatus.MANUAL_REVIEW):
            # Flag for manual review rather than rejecting
            final_status = PaymentStatus.MANUAL_REVIEW
            verif_reason = f"Transaction ID verified. Proof flagged for manual organizer review by AI Fraud Screening ({ai_model}): {ai_reason}"
        else:
            final_status = PaymentStatus.TRANSACTION_ID_VERIFIED
            verif_reason = "Transaction ID verified successfully against payment screenshot. Awaiting organizer approval."
    else:
        # Fallback when OCR yields no text (e.g. Tesseract binary not present on local machine)
        if not _configure_tesseract():
            final_status = PaymentStatus.MANUAL_REVIEW
            if fraud_status in (FraudStatus.SUSPICIOUS, FraudStatus.MANUAL_REVIEW):
                verif_reason = f"Automated OCR engine is offline; flagged for manual review due to {fraud_status} risk: {ai_reason}"
            else:
                verif_reason = "Payment proof submitted. Automated OCR engine is offline; queued for manual organizer review."
        else:
            final_status = PaymentStatus.PAYMENT_VERIFICATION_FAILED
            verif_reason = "Transaction ID does not match the payment screenshot. Please check your Transaction ID and upload the correct payment screenshot."
            reasons.append(verif_reason)

    # 9. Upsert Payment Record
    final_extracted_id = extracted_txn_id or (clean_entered_txn if is_txn_match else None)
    payment = _upsert_payment_record(
        registration=registration,
        event=event,
        student=student,
        expected_amount=expected_amount,
        detected_amount=detected_amount,
        transaction_id=clean_entered_txn,
        extracted_transaction_id=final_extracted_id,
        screenshot_path=relative_storage_path,
        screenshot_hash=screenshot_hash,
        status=final_status,
        fraud_risk=fraud_risk,
        fraud_details=json.dumps(fraud_indicators),
        ocr_data=json.dumps(parsed),
        verification_reason=verif_reason,
        fraud_status=fraud_status,
        fraud_score=ai_conf,
        fraud_label=ai_label,
        fraud_model=ai_model,
        fraud_checked_at=datetime.utcnow()
    )

    return payment, {
        'status': final_status,
        'fraud_risk': fraud_risk,
        'fraud_status': fraud_status,
        'fraud_score': ai_conf,
        'fraud_label': ai_label,
        'fraud_model': ai_model,
        'message': verif_reason,
        'reasons': reasons or fraud_indicators
    }


def _upsert_payment_record(registration, event, student, expected_amount, detected_amount,
                           transaction_id, extracted_transaction_id, screenshot_path, screenshot_hash, status,
                           fraud_risk, fraud_details, ocr_data, verification_reason,
                           fraud_status=None, fraud_score=None, fraud_label=None, fraud_model=None, fraud_checked_at=None):
    """Helper to persist or update a Payment record with AI fraud audit fields."""
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
            extracted_transaction_id=extracted_transaction_id,
            payment_method='UPI_DIRECT',
            payment_screenshot=screenshot_path,
            screenshot_hash=screenshot_hash,
            status=status,
            fraud_risk=fraud_risk,
            fraud_details=fraud_details,
            ocr_extracted_data=ocr_data,
            verification_reason=verification_reason,
            fraud_status=fraud_status,
            fraud_score=fraud_score,
            fraud_label=fraud_label,
            fraud_model=fraud_model,
            fraud_checked_at=fraud_checked_at or datetime.utcnow(),
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
        payment.extracted_transaction_id = extracted_transaction_id
        payment.payment_screenshot = screenshot_path
        payment.screenshot_hash = screenshot_hash
        payment.status = status
        payment.fraud_risk = fraud_risk
        payment.fraud_details = fraud_details
        payment.ocr_extracted_data = ocr_data
        payment.verification_reason = verification_reason
        if fraud_status is not None:
            payment.fraud_status = fraud_status
        if fraud_score is not None:
            payment.fraud_score = fraud_score
        if fraud_label is not None:
            payment.fraud_label = fraud_label
        if fraud_model is not None:
            payment.fraud_model = fraud_model
        if fraud_checked_at is not None:
            payment.fraud_checked_at = fraud_checked_at
        payment.submitted_at = datetime.utcnow()

    db.session.commit()
    return payment
