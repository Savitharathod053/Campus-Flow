import os
import re
import io
import shutil
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter
from pypdf import PdfReader
from flask import current_app

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

    # Check Flask config / env variable
    custom_cmd = ""
    try:
        custom_cmd = current_app.config.get('TESSERACT_CMD') or os.environ.get('TESSERACT_CMD', '')
    except RuntimeError:
        custom_cmd = os.environ.get('TESSERACT_CMD', '')

    if custom_cmd and os.path.exists(custom_cmd):
        pytesseract.pytesseract.tesseract_cmd = custom_cmd
        return True

    # If tesseract is directly in PATH
    if shutil.which('tesseract'):
        return True

    # Standard Windows install locations
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


def extract_text_from_pdf(pdf_path):
    """
    Extracts text from a PDF file using pypdf.
    If the PDF is scanned/image-based, falls back to OCR on embedded images.
    """
    text_content = []
    try:
        reader = PdfReader(str(pdf_path))
        for page_idx, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            if page_text.strip():
                text_content.append(page_text)
            else:
                # If page text is blank, attempt image extraction & OCR
                if PYTESSERACT_AVAILABLE and _configure_tesseract() and hasattr(page, 'images'):
                    try:
                        for img_file in page.images:
                            image = Image.open(io.BytesIO(img_file.data))
                            ocr_text = pytesseract.image_to_string(image)
                            if ocr_text.strip():
                                text_content.append(ocr_text)
                    except Exception:
                        pass
    except Exception as e:
        return f"[PDF Read Error: {str(e)}]"

    return "\n".join(text_content).strip()


def extract_text_from_image(image_path):
    """
    Performs OCR on an image file (PNG, JPG, JPEG, WEBP) using pytesseract.
    """
    if not PYTESSERACT_AVAILABLE or not _configure_tesseract():
        return ""

    try:
        with Image.open(str(image_path)) as img:
            # Preprocess image for OCR accuracy: convert to grayscale and enhance contrast
            gray_img = img.convert('L')
            enhancer = ImageEnhance.Contrast(gray_img)
            enhanced_img = enhancer.enhance(2.0)
            
            text = pytesseract.image_to_string(enhanced_img)
            if not text.strip():
                # Fallback to raw image OCR if contrast enhancement yielded nothing
                text = pytesseract.image_to_string(img)
            return text.strip()
    except Exception as e:
        return f"[Image OCR Error: {str(e)}]"


def extract_text_from_file(file_path):
    """
    Automatically dispatches text extraction based on file extension.
    Returns extracted text string.
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == '.pdf':
        return extract_text_from_pdf(path)
    elif ext in ('.png', '.jpg', '.jpeg', '.webp'):
        return extract_text_from_image(path)
    return ""


def extract_roll_number(text, custom_pattern=None, candidate_roll_numbers=None, filename=None):
    """
    Identifies a student roll number from extracted text using a multi-stage matcher:
    1. Direct match against known registered roll numbers for the event.
    2. Configurable regex patterns for labelled roll numbers (e.g. "Roll No: 23DS001").
    3. Standard college roll number format patterns.
    4. Heuristic search in the filename.
    
    Returns normalized uppercase roll number or None.
    """
    clean_text = text or ""
    
    # 1. Candidate Roll Numbers Matching (highest precision for registered students)
    if candidate_roll_numbers:
        # Create a lookup mapping lowercase to canonical roll number
        for candidate in candidate_roll_numbers:
            cand_clean = candidate.strip().upper()
            if not cand_clean:
                continue
            # Look for exact word boundary match in text
            escaped = re.escape(cand_clean)
            if re.search(rf'(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])', clean_text, re.IGNORECASE):
                return cand_clean

    # 2. Configurable / Default Regex Patterns
    patterns = []
    if custom_pattern:
        patterns.append(custom_pattern)

    # Add default configurable patterns
    default_pattern = None
    try:
        default_pattern = current_app.config.get('ROLL_NUMBER_REGEX_PATTERN')
    except RuntimeError:
        default_pattern = os.environ.get('ROLL_NUMBER_REGEX_PATTERN')

    if default_pattern and default_pattern not in patterns:
        patterns.append(default_pattern)

    # Standard fallback patterns
    fallback_patterns = [
        r'(?:roll\s*(?:no|number|num)?|student\s*id|reg(?:istration)?\s*(?:no|number|num)?|enrollment\s*(?:no|number|num)?|uid)\s*[:\-#.\s]\s*([A-Za-z0-9\-_/]{3,30})',
        r'\b([0-9]{2}[A-Za-z]{2,5}[0-9]{2,6})\b',
        r'\b([0-9]{4}[A-Za-z]{2,5}[0-9]{2,6})\b',
        r'\b([A-Za-z]{2,4}[0-9]{2}[A-Za-z]{1,3}[0-9]{2,5})\b'
    ]
    for p in fallback_patterns:
        if p not in patterns:
            patterns.append(p)

    for pat in patterns:
        try:
            match = re.search(pat, clean_text, re.IGNORECASE)
            if match:
                # Capture group 1 if present, else whole match
                val = match.group(1) if match.groups() else match.group(0)
                cleaned_val = re.sub(r'[^A-Za-z0-9\-_/]', '', val).strip().upper()
                if len(cleaned_val) >= 3:
                    # If candidate_roll_numbers given, check if it maps to one
                    if candidate_roll_numbers:
                        for cand in candidate_roll_numbers:
                            if cand.strip().upper() == cleaned_val:
                                return cand.strip().upper()
                    return cleaned_val
        except re.error:
            continue

    # 3. Filename Heuristic Check
    if filename:
        fn_clean = Path(filename).stem
        if candidate_roll_numbers:
            for candidate in candidate_roll_numbers:
                cand_clean = candidate.strip().upper()
                if cand_clean and cand_clean in fn_clean.upper():
                    return cand_clean

        for pat in patterns:
            try:
                m = re.search(pat, fn_clean, re.IGNORECASE)
                if m:
                    val = m.group(1) if m.groups() else m.group(0)
                    cleaned_val = re.sub(r'[^A-Za-z0-9\-_/]', '', val).strip().upper()
                    if len(cleaned_val) >= 3:
                        return cleaned_val
            except re.error:
                continue

    return None
