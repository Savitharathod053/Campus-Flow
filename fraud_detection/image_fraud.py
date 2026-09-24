"""
Campus Flow - Payment Screenshot Fraud Detection Module
image_fraud.py

Integrates pre-trained Hugging Face vision models to detect AI-generated, synthetic,
or manipulated payment screenshots (UPI/Bank receipts).

Key Features:
- Safe image loading (MIME check, magic bytes check, Pillow verification, size & decompression bomb guards).
- Configurable pre-trained Hugging Face image classification model via HF_FRAUD_MODEL env var.
  Default: 'umm-maybe/AI-image-detector' (ViT model trained for AI-generated vs real detection).
- Fallback & resilience: If model is downloading, offline, or unavailable, fails safely
  to 'MANUAL_REVIEW' without crashing checkout/registration flows.
- Thread-safe singleton model pipeline loader for optimal memory & inference performance.
- Human-in-the-loop compliance: Model is an advisory risk signal, not an automated payment decider.
"""

import os
import io
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image

logger = logging.getLogger("CampusFlow.FraudDetection")

# Configurable constants
DEFAULT_HF_MODEL = "umm-maybe/AI-image-detector"
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
ALLOWED_MIMETYPES = {'image/png', 'image/jpeg', 'image/webp'}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PIXELS = 25_000_000  # Guard against decompression bombs
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# Known AI / Fake / Synthetic class labels across popular HF detector models
SUSPICIOUS_LABELS = {
    'artificial', 'fake', 'synthetic', 'ai', 'ai-generated', 'deepfake',
    'manipulated', 'tampered', 'generated', 'cg', 'fake_image'
}
HUMAN_REAL_LABELS = {
    'human', 'real', 'authentic', 'natural', 'real_image', 'original'
}


class FraudStatus:
    LOW_RISK = "LOW_RISK"
    SUSPICIOUS = "SUSPICIOUS"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    VERIFIED = "VERIFIED"

    CHOICES = [LOW_RISK, SUSPICIOUS, MANUAL_REVIEW, VERIFIED]


# Thread-safe pipeline cache
_PIPELINE_LOCK = threading.Lock()
_CACHED_MODEL_NAME: Optional[str] = None
_CACHED_PIPELINE = None


def get_model_name() -> str:
    """
    Returns the configured Hugging Face model identifier from environment.
    Defaults to 'umm-maybe/AI-image-detector'.
    """
    return os.environ.get("HF_FRAUD_MODEL", DEFAULT_HF_MODEL).strip() or DEFAULT_HF_MODEL


def _get_classification_pipeline(model_name: str):
    """
    Lazily initializes and caches the Hugging Face image classification pipeline.
    Thread-safe singleton pattern.
    """
    global _CACHED_PIPELINE, _CACHED_MODEL_NAME
    if _CACHED_PIPELINE is not None and _CACHED_MODEL_NAME == model_name:
        return _CACHED_PIPELINE

    with _PIPELINE_LOCK:
        if _CACHED_PIPELINE is not None and _CACHED_MODEL_NAME == model_name:
            return _CACHED_PIPELINE

        try:
            from transformers import pipeline
            import torch
        except ImportError as e:
            logger.warning(
                f"Transformers or PyTorch not available ({e}). "
                "Hugging Face fraud detection will operate in fallback mode."
            )
            return None

        try:
            device = 0 if torch.cuda.is_available() else -1
            logger.info(f"Loading Hugging Face image classification pipeline for '{model_name}' on device {device}...")
            pipe = pipeline(
                "image-classification",
                model=model_name,
                device=device
            )
            _CACHED_PIPELINE = pipe
            _CACHED_MODEL_NAME = model_name
            logger.info(f"Hugging Face fraud model '{model_name}' loaded successfully.")
            return _CACHED_PIPELINE
        except Exception as exc:
            logger.error(f"Failed to load Hugging Face model '{model_name}': {exc}", exc_info=True)
            return None


def _validate_image_security(image_path: Path) -> Optional[str]:
    """
    Validates file existence, path traversal safety, extension, file size,
    and image magic bytes/header. Returns error message if invalid, None if safe.
    """
    try:
        resolved_path = image_path.resolve()
        if not resolved_path.is_file():
            return "File does not exist or is not a regular file."

        # Extension check
        ext = resolved_path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}."

        # File size check
        file_size = resolved_path.stat().st_size
        if file_size <= 0:
            return "Uploaded image file is empty (0 bytes)."
        if file_size > MAX_FILE_SIZE_BYTES:
            max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
            return f"Uploaded image exceeds maximum allowable size of {max_mb}MB."

        # Magic bytes / header inspection
        with open(resolved_path, "rb") as f:
            header = f.read(16)

        is_png = header.startswith(b"\x89PNG\r\n\x1a\n")
        is_jpeg = header.startswith(b"\xff\xd8\xff")
        is_webp = len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP"

        if not (is_png or is_jpeg or is_webp):
            return "File signature does not match a valid PNG, JPEG, or WEBP image."

        return None
    except Exception as e:
        return f"Image validation error: {str(e)}"


def check_payment_image(image_path: str | Path) -> Dict[str, Any]:
    """
    Main public API for screening payment proof screenshots.
    
    1. Loads the uploaded image safely.
    2. Validates supported extension, MIME signature, and PIL integrity.
    3. Checks file size and resolution limits.
    4. Preprocesses the image safely to standard RGB.
    5. Runs Hugging Face inference against configured model (HF_FRAUD_MODEL).
    6. Returns structured risk information:
       {
           "is_suspicious": bool,
           "confidence": float,
           "label": str,
           "reason": str,
           "model": str,
           "fraud_status": "LOW_RISK" | "SUSPICIOUS" | "MANUAL_REVIEW"
       }
    """
    model_name = get_model_name()
    path = Path(image_path)

    # 1. Safe Security & Format Validation
    validation_err = _validate_image_security(path)
    if validation_err:
        logger.warning(f"Payment proof validation rejected '{path}': {validation_err}")
        return {
            "is_suspicious": True,
            "confidence": 0.0,
            "label": "INVALID_IMAGE",
            "reason": f"Security check failed: {validation_err}",
            "model": model_name,
            "fraud_status": FraudStatus.MANUAL_REVIEW
        }

    # 2. PIL Safe Loading & Integrity Verification
    pil_img: Optional[Image.Image] = None
    try:
        # Step A: verify image structure integrity
        with Image.open(str(path)) as test_img:
            test_img.verify()

        # Step B: reopen to process (verify() closes file and marks image consumed)
        with Image.open(str(path)) as opened_img:
            # Check dimensions sanity
            width, height = opened_img.size
            if width < 50 or height < 50:
                return {
                    "is_suspicious": True,
                    "confidence": 0.85,
                    "label": "ABNORMAL_DIMENSIONS",
                    "reason": f"Image dimensions too small ({width}x{height}px) for a mobile receipt screenshot.",
                    "model": model_name,
                    "fraud_status": FraudStatus.MANUAL_REVIEW
                }

            # Convert to standard RGB and copy into memory to release file handle
            pil_img = opened_img.convert("RGB")
            # Downscale if image is needlessly massive to avoid CPU/GPU memory exhaustion
            if max(pil_img.size) > 1600:
                pil_img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    except Exception as exc:
        logger.warning(f"PIL verification failed for '{path}': {exc}")
        return {
            "is_suspicious": True,
            "confidence": 0.0,
            "label": "CORRUPT_IMAGE",
            "reason": f"Image could not be parsed safely: {str(exc)}",
            "model": model_name,
            "fraud_status": FraudStatus.MANUAL_REVIEW
        }

    # 3. Model Inference Pipeline
    pipe = _get_classification_pipeline(model_name)
    if pipe is None:
        # Fallback when ML engine is offline / not yet loaded
        logger.info(f"Hugging Face pipeline unavailable for {model_name}; returning safe manual review state.")
        return {
            "is_suspicious": False,
            "confidence": 0.0,
            "label": "MODEL_OFFLINE",
            "reason": "AI fraud detection model is currently offline or warming up. Submission queued for manual verification.",
            "model": model_name,
            "fraud_status": FraudStatus.MANUAL_REVIEW
        }

    try:
        # Run inference
        outputs = pipe(pil_img)
        # Hugging Face image classification outputs list of dicts:
        # [{'label': 'artificial', 'score': 0.89}, {'label': 'human', 'score': 0.11}]
        if not outputs or not isinstance(outputs, list):
            raise ValueError(f"Unexpected model output format: {outputs}")

        top_pred = outputs[0]
        top_label = str(top_pred.get("label", "")).strip().lower()
        top_score = float(top_pred.get("score", 0.0))

        # Check secondary predictions for suspicious tags
        suspicious_score = 0.0
        human_score = 0.0
        for item in outputs:
            lbl = str(item.get("label", "")).strip().lower()
            score = float(item.get("score", 0.0))
            if any(s in lbl for s in SUSPICIOUS_LABELS):
                if score > suspicious_score:
                    suspicious_score = score
            if any(h in lbl for h in HUMAN_REAL_LABELS):
                if score > human_score:
                    human_score = score

        # Determine risk assessment
        # If top label is explicitly artificial / synthetic / fake
        is_top_suspicious = any(s in top_label for s in SUSPICIOUS_LABELS)
        
        if is_top_suspicious and top_score >= 0.75:
            fraud_status = FraudStatus.SUSPICIOUS
            is_suspicious = True
            confidence = round(top_score, 4)
            reason = (
                f"Model detected high probability ({confidence * 100:.1f}%) of synthetic or "
                f"AI-generated manipulation (classified as '{top_label}')."
            )
        elif is_top_suspicious and top_score >= 0.50:
            fraud_status = FraudStatus.MANUAL_REVIEW
            is_suspicious = True
            confidence = round(top_score, 4)
            reason = (
                f"Moderate probability ({confidence * 100:.1f}%) of synthetic patterns "
                f"(classified as '{top_label}'). Recommended for manual organizer review."
            )
        elif suspicious_score >= 0.40:
            fraud_status = FraudStatus.MANUAL_REVIEW
            is_suspicious = True
            confidence = round(suspicious_score, 4)
            reason = (
                f"Elevated secondary manipulation indicator detected ({confidence * 100:.1f}%). "
                "Recommended for manual verification."
            )
        else:
            fraud_status = FraudStatus.LOW_RISK
            is_suspicious = False
            confidence = round(human_score if human_score > 0 else (1.0 - suspicious_score), 4)
            reason = f"Image shows natural mobile capture characteristics (classified as '{top_label}' with {top_score * 100:.1f}% confidence)."

        return {
            "is_suspicious": is_suspicious,
            "confidence": confidence,
            "label": top_label,
            "reason": reason,
            "model": model_name,
            "fraud_status": fraud_status
        }

    except Exception as infer_err:
        logger.error(f"Inference error with model '{model_name}': {infer_err}", exc_info=True)
        return {
            "is_suspicious": False,
            "confidence": 0.0,
            "label": "INFERENCE_ERROR",
            "reason": f"AI model inference encountered a temporary issue ({str(infer_err)}). Queued for manual organizer review.",
            "model": model_name,
            "fraud_status": FraudStatus.MANUAL_REVIEW
        }
