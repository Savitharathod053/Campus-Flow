import os
import re
import uuid
import mimetypes
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse
import requests
from flask import current_app, url_for

logger = logging.getLogger(__name__)

# In-memory flag so bucket check runs once per application lifecycle
_BUCKET_VERIFIED = set()
_RESOLVED_BUCKETS = {}


def is_production_env() -> bool:
    """Detects whether running in production (Railway, Render, or FLASK_ENV=production)."""
    return bool(
        os.environ.get('RAILWAY_ENVIRONMENT') or
        os.environ.get('RAILWAY_ENVIRONMENT_NAME') or
        os.environ.get('RAILWAY_PROJECT_ID') or
        os.environ.get('RAILWAY_PUBLIC_DOMAIN') or
        os.environ.get('RAILWAY_STATIC_URL') or
        os.environ.get('RENDER') or 
        os.environ.get('FLASK_ENV', '').lower() == 'production' or
        os.environ.get('ENVIRONMENT', '').lower() == 'production'
    )


def is_cloud_storage_enabled() -> bool:
    """
    Returns True if Supabase Cloud Storage is configured with URL and Service Role Key.
    """
    supabase_url = get_supabase_url()
    service_key = get_supabase_service_key()
    return bool(supabase_url and service_key)


def get_supabase_url() -> str:
    """Returns normalized Supabase project base URL."""
    val = ''
    if current_app:
        val = (
            current_app.config.get('SUPABASE_URL', '') or
            current_app.config.get('SUPABASE_PROJECT_URL', '') or
            current_app.config.get('NEXT_PUBLIC_SUPABASE_URL', '')
        )
    if not val:
        val = (
            os.environ.get('SUPABASE_URL', '') or
            os.environ.get('SUPABASE_PROJECT_URL', '') or
            os.environ.get('NEXT_PUBLIC_SUPABASE_URL', '')
        )
    return val.strip().rstrip('/')


def get_supabase_service_key() -> str:
    """Returns Supabase Service Role Key, Secret Key, or API Key."""
    val = ''
    if current_app:
        val = (
            current_app.config.get('SUPABASE_SERVICE_ROLE_KEY', '') or
            current_app.config.get('SUPABASE_SERVICE_KEY', '') or
            current_app.config.get('SUPABASE_SECRET_KEY', '') or
            current_app.config.get('SUPABASE_KEY', '') or
            current_app.config.get('SUPABASE_ANON_KEY', '') or
            current_app.config.get('SUPABASE_PUBLISHABLE_KEY', '')
        )
    if not val:
        val = (
            os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '') or
            os.environ.get('SUPABASE_SERVICE_KEY', '') or
            os.environ.get('SUPABASE_SECRET_KEY', '') or
            os.environ.get('SUPABASE_KEY', '') or
            os.environ.get('SUPABASE_ANON_KEY', '') or
            os.environ.get('SUPABASE_PUBLISHABLE_KEY', '')
        )
    return val.strip()


def get_storage_bucket(default: str = 'payment-proofs') -> str:
    """Returns Supabase storage bucket name (configurable via SUPABASE_STORAGE_BUCKET or STORAGE_BUCKET, default 'payment-proofs')."""
    val = ''
    if current_app:
        val = current_app.config.get('SUPABASE_STORAGE_BUCKET', '') or current_app.config.get('STORAGE_BUCKET', '')
    if not val:
        val = os.environ.get('SUPABASE_STORAGE_BUCKET', '') or os.environ.get('STORAGE_BUCKET', '')
    if not val:
        val = default
    clean = val.strip().strip("'\"")
    return clean or default


def normalize_storage_folder(folder: str) -> str:
    """
    Normalizes folder names into consistent logical folders inside the single 'payment-proof' Supabase bucket:
    - payment-proofs (student receipts)
    - event-images (event posters)
    - organizer-qrs (organizer UPI payment QR codes)
    - certificates (student certificates)
    - qrcodes (ticket QR codes)
    """
    clean = (folder or '').strip().strip('/')
    if not clean:
        return 'event-images'

    if clean in ('event_images', 'posters'):
        return 'event-images'
    elif clean in ('organizer_qrs', 'organizer_qr'):
        return 'organizer-qrs'
    elif clean in ('payment_proofs', 'payment_proof'):
        return 'payment-proofs'
    elif clean.startswith('event_') and ('/student_' in clean or 'student_' in clean):
        # Format: event_{event_id}/student_{student_id} -> payment-proofs/event_{event_id}/student_{student_id}
        return f"payment-proofs/{clean}"
    return clean


def sanitize_storage_filename(filename: str, prefix: str = "") -> str:
    """
    Safely sanitizes incoming filenames (especially WhatsApp screenshots like:
    'WhatsApp Image 2026-03-24 at 10.45.12 (1).jpeg').
    Removes spaces, parentheses, brackets, and invalid characters, converting to URL-safe alphanumeric slugs.
    Appends a timestamp and unique token to prevent collisions unless already sanitized.
    """
    if not filename:
        filename = "upload.bin"

    # Extract extension
    base, ext = os.path.splitext(filename)
    ext = ext.lower().strip()
    if not ext and '.' in filename:
        ext = '.' + filename.rsplit('.', 1)[-1].lower()
    
    # Common extension normalization
    if ext in ('.jpeg', '.jpg'):
        ext = '.jpg'
    elif ext == '.png':
        ext = '.png'
    elif ext == '.webp':
        ext = '.webp'
    elif ext == '.pdf':
        ext = '.pdf'

    # Check if already uniquely formatted with timestamp and token
    if re.search(r'\d{10}_[0-9a-f]{8}_', base):
        clean_name = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', filename)
        return clean_name

    # Clean base: replace all non-alphanumeric (except underscores and hyphens) with underscore
    clean_base = re.sub(r'[^a-zA-Z0-9_\-]', '_', base)
    clean_base = re.sub(r'_+', '_', clean_base).strip('_')
    if not clean_base:
        clean_base = "file"

    timestamp = int(datetime.utcnow().timestamp())
    random_token = uuid.uuid4().hex[:8]
    pfx = f"{prefix.strip('_')}_" if prefix else ""
    return f"{pfx}{timestamp}_{random_token}_{clean_base[:40]}{ext}"


def check_bucket_exists(bucket_name: str = None) -> tuple[bool, str | None]:
    """
    Checks if the specified Supabase storage bucket exists.
    If missing, attempts to create it as a public bucket.
    Returns (exists: bool, error_message: str | None).
    """
    if not is_cloud_storage_enabled():
        return True, None

    bucket = bucket_name or get_storage_bucket()
    if bucket in _BUCKET_VERIFIED:
        return True, None

    supabase_url = get_supabase_url()
    service_key = get_supabase_service_key()
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
        "Content-Type": "application/json"
    }

    try:
        # Check if bucket exists
        get_res = requests.get(
            f"{supabase_url}/storage/v1/bucket/{bucket}",
            headers=headers,
            timeout=8
        )
        if get_res.status_code == 200:
            _BUCKET_VERIFIED.add(bucket)
            return True, None

        if get_res.status_code in (401, 403):
            err_msg = (
                f"Supabase Storage authentication failed (HTTP {get_res.status_code}). "
                "Please verify SUPABASE_SERVICE_ROLE_KEY is configured with your service_role secret key (starts with 'eyJ...'), "
                "not the client publishable/anon key."
            )
            logger.error(f"[Storage] {err_msg}")
            return False, err_msg

        if get_res.status_code == 404 or (get_res.status_code == 400 and 'NoSuchBucket' in get_res.text):
            # Check if plural or singular counterpart bucket exists in Supabase
            alt_bucket = 'payment-proofs' if bucket == 'payment-proof' else ('payment-proof' if bucket == 'payment-proofs' else None)
            if alt_bucket:
                try:
                    alt_res = requests.get(
                        f"{supabase_url}/storage/v1/bucket/{alt_bucket}",
                        headers=headers,
                        timeout=8
                    )
                    if alt_res.status_code == 200:
                        _BUCKET_VERIFIED.add(bucket)
                        _BUCKET_VERIFIED.add(alt_bucket)
                        _RESOLVED_BUCKETS[bucket] = alt_bucket
                        logger.info(f"[Supabase Storage] Resolved requested bucket '{bucket}' to existing bucket '{alt_bucket}'")
                        return True, None
                except Exception:
                    pass

            # Attempt to create bucket with public access
            post_res = requests.post(
                f"{supabase_url}/storage/v1/bucket",
                headers=headers,
                json={
                    "id": bucket,
                    "name": bucket,
                    "public": True
                },
                timeout=8
            )
            if post_res.status_code in (200, 201):
                logger.info(f"[Supabase Storage] Successfully created public bucket '{bucket}'")
                _BUCKET_VERIFIED.add(bucket)
                return True, None
            elif post_res.status_code in (400, 409) and ('already exists' in post_res.text.lower() or 'duplicate' in post_res.text.lower()):
                _BUCKET_VERIFIED.add(bucket)
                return True, None
            else:
                err_msg = (
                    f"Supabase Storage bucket '{bucket}' was not found and automatic creation failed (HTTP {post_res.status_code}: {post_res.text}). "
                    f"Please ensure bucket '{bucket}' exists and is marked Public in your Supabase Dashboard."
                )
                logger.error(f"[Storage] {err_msg}")
                return False, err_msg

        err_msg = f"Supabase Storage bucket '{bucket}' check failed (HTTP {get_res.status_code}): {get_res.text}"
        logger.error(f"[Storage] {err_msg}")
        return False, err_msg
    except Exception as exc:
        err_msg = f"Supabase Storage connection error: {str(exc)}"
        logger.exception(f"[Storage] Cloud storage bucket check failed: {err_msg}")
        return False, err_msg


def ensure_bucket_exists(bucket_name: str = None) -> bool:
    """
    Ensures the specified Supabase storage bucket exists and is marked public.
    """
    exists, _ = check_bucket_exists(bucket_name)
    return exists


def upload_file(
    file_data,
    folder: str = "event-images",
    filename: str = None,
    content_type: str = None,
    prefix: str = "",
    bucket_name: str = None
) -> tuple[bool, str | None, str | None]:
    """
    Uploads a file directly to persistent Supabase Cloud Storage.
    - In production or whenever Supabase credentials are configured: uploads strictly to Supabase Storage.
    - If upload fails, returns (False, None, error_message). NEVER silently falls back to ephemeral disk in production.
    - Local fallback is permitted ONLY in offline local development environments where no cloud URL is configured.

    Arguments:
    - file_data: bytes, file-like object, Werkzeug FileStorage, or local filesystem path (str/Path)
    - folder: logical folder ('payment-proofs', 'event-images', 'organizer-qrs', 'certificates', etc.)
    - filename: original file name
    - content_type: MIME type (auto-detected if None)
    - prefix: optional prefix for sanitized file name
    - bucket_name: optional bucket name (defaults to SUPABASE_STORAGE_BUCKET or 'payment-proof')

    Returns:
    - (success: bool, public_url: str | None, error_or_storage_path: str | None)
    """
    # 1. Resolve raw bytes and filename
    orig_filename = filename
    if hasattr(file_data, 'filename') and not orig_filename:
        orig_filename = file_data.filename
    elif isinstance(file_data, (str, Path)) and not orig_filename:
        orig_filename = Path(file_data).name

    sanitized_filename = sanitize_storage_filename(orig_filename or 'upload.bin', prefix=prefix)

    # Read binary bytes
    try:
        if isinstance(file_data, (str, Path)):
            with open(file_data, 'rb') as f:
                binary_content = f.read()
        elif hasattr(file_data, 'read'):
            file_data.seek(0)
            binary_content = file_data.read()
        elif isinstance(file_data, bytes):
            binary_content = file_data
        else:
            return False, None, "Invalid file data provided"
    except Exception as exc:
        logger.error(f"[Storage] Failed reading file data: {exc}")
        return False, None, f"Failed reading file data: {str(exc)}"

    if not binary_content:
        return False, None, "Uploaded file content is empty"

    # Guess MIME type
    if not content_type:
        guessed_type, _ = mimetypes.guess_type(sanitized_filename)
        content_type = guessed_type or 'application/octet-stream'

    # Normalize folder path to target logical folders within the single 'payment-proof' bucket
    clean_folder = normalize_storage_folder(folder)

    # 2. Upload to Supabase Storage
    if is_cloud_storage_enabled():
        bucket = bucket_name or get_storage_bucket()
        bucket_exists, bucket_err = check_bucket_exists(bucket)
        if not bucket_exists:
            err_msg = bucket_err or f"Supabase Storage bucket '{bucket}' is not available."
            logger.error(f"[Storage] Cloud storage upload blocked: {err_msg}")
            return False, None, err_msg

        actual_bucket = _RESOLVED_BUCKETS.get(bucket, bucket)
        storage_path = f"{clean_folder}/{sanitized_filename}"
        supabase_url = get_supabase_url()
        service_key = get_supabase_service_key()

        upload_endpoint = f"{supabase_url}/storage/v1/object/{actual_bucket}/{storage_path}"
        headers = {
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Content-Type": content_type,
            "x-upsert": "true"
        }

        try:
            resp = requests.post(
                upload_endpoint,
                headers=headers,
                data=binary_content,
                timeout=30
            )

            if resp.status_code in (200, 201):
                encoded_path = "/".join(quote(p) for p in storage_path.split('/'))
                public_url = f"{supabase_url}/storage/v1/object/public/{actual_bucket}/{encoded_path}"
                logger.info(f"[Storage] Successfully uploaded '{storage_path}' to Supabase -> {public_url}")
                return True, public_url, storage_path
            else:
                err_msg = f"Supabase upload failed (HTTP {resp.status_code}): {resp.text}"
                logger.error(f"[Storage] {err_msg}")
                # STRICT: Do NOT silently fall back to local ephemeral container disk!
                return False, None, err_msg
        except Exception as exc:
            err_msg = f"Supabase Storage network error: {str(exc)}"
            logger.exception(f"[Storage] {err_msg}")
            # STRICT: Do NOT silently fall back to local ephemeral container disk!
            return False, None, err_msg

    # 3. Production check: If running in production but cloud storage is not configured, FAIL explicitly
    if is_production_env() or get_supabase_url():
        err_msg = (
            "Persistent Cloud Storage error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for file storage. "
            "Railway ephemeral container filesystem cannot be used for permanent uploads."
        )
        logger.error(f"[Storage] {err_msg}")
        return False, None, err_msg

    # 4. Offline local development fallback only (when neither production nor cloud URL is active)
    try:
        logger.warning("[Storage] Cloud storage not configured. Saving to local development uploads directory.")
        if current_app:
            base_upload_dir = Path(current_app.config.get('UPLOAD_FOLDER') or (Path(current_app.root_path) / 'static' / 'uploads'))
        else:
            base_upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads'

        target_dir = base_upload_dir / clean_folder
        target_dir.mkdir(parents=True, exist_ok=True)

        local_file_path = target_dir / sanitized_filename
        with open(local_file_path, 'wb') as f:
            f.write(binary_content)

        relative_path = f"uploads/{clean_folder}/{sanitized_filename}"
        try:
            local_url = url_for('static', filename=relative_path)
        except Exception:
            local_url = f"/static/{relative_path}"

        logger.info(f"[LocalStorage] Saved '{relative_path}' for offline development")
        return True, local_url, relative_path
    except Exception as exc:
        err_msg = f"Failed to save file to local filesystem: {str(exc)}"
        logger.error(f"[LocalStorage] {err_msg}")
        return False, None, err_msg


def delete_file(file_identifier: str) -> bool:
    """
    Deletes a file from Supabase Storage and/or local filesystem.
    Accepts full URL, Supabase storage path, or local static path.
    """
    if not file_identifier:
        return True

    # 1. Check if Supabase Storage URL or path
    supabase_url = get_supabase_url()
    bucket = _RESOLVED_BUCKETS.get(get_storage_bucket(), get_storage_bucket())

    is_supabase_url = supabase_url and file_identifier.startswith(supabase_url)
    known_storage_folders = (
        'payment-proofs', 'event-images', 'organizer-qrs', 'certificates', 'qrcodes',
        'organizer_qrs', 'payment_proofs', 'event_images', 'posters'
    )
    is_supabase_path = any(
        file_identifier.startswith(f"{folder}/") 
        for folder in known_storage_folders
    ) or file_identifier.startswith('event_')

    if (is_supabase_url or is_supabase_path) and is_cloud_storage_enabled():
        target_bucket = bucket
        if is_supabase_url:
            for b in (bucket, 'payment-proofs', 'payment-proof'):
                marker = f"/object/public/{b}/"
                if marker in file_identifier:
                    storage_path = file_identifier.split(marker, 1)[-1]
                    target_bucket = b
                    break
            else:
                storage_path = Path(urlparse(file_identifier).path).name
        else:
            storage_path = file_identifier

        service_key = get_supabase_service_key()
        headers = {
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key
        }
        delete_endpoint = f"{supabase_url}/storage/v1/object/{target_bucket}/{storage_path}"
        try:
            resp = requests.delete(delete_endpoint, headers=headers, timeout=10)
            if resp.status_code in (200, 204):
                logger.info(f"[Supabase Storage] Deleted '{storage_path}'")
        except Exception as exc:
            logger.warning(f"[Supabase Storage] Error deleting '{storage_path}': {exc}")

    # 2. Also safely remove local copy if exists
    try:
        clean_path = file_identifier.replace('static/', '').lstrip('/')
        if clean_path.startswith(('http://', 'https://')):
            return True
        if current_app:
            local_target = Path(current_app.root_path) / 'static' / clean_path
        else:
            local_target = Path(__file__).resolve().parent.parent / 'static' / clean_path

        if local_target.exists() and local_target.is_file():
            local_target.unlink(missing_ok=True)
            logger.info(f"[LocalStorage] Unlinked '{local_target}'")
    except Exception:
        pass

    return True


def get_media_url(file_identifier: str, default: str = None) -> str | None:
    """
    Resolves any file identifier (Supabase public URL, Supabase storage path,
    or local uploads path) to an accessible URL for the browser.
    Returns None (or default) if missing or unavailable.
    """
    if not file_identifier or not str(file_identifier).strip():
        return default

    clean = str(file_identifier).strip()

    # 1. Already a full absolute URL
    if clean.startswith(('http://', 'https://')):
        return clean

    # 2. Supabase storage path (e.g. 'organizer-qrs/filename.png', 'payment-proofs/event_1/student_2/filename.jpg')
    known_folders = (
        'payment-proofs', 'event-images', 'organizer-qrs', 'certificates', 'qrcodes',
        'organizer_qrs', 'payment_proofs', 'event_images', 'posters'
    )
    is_cloud_path = (
        any(clean.startswith(f"{f}/") for f in known_folders) or
        clean.startswith('event_') or
        bool(re.match(r'^event_\d+/', clean))
    )

    if is_cloud_path and is_cloud_storage_enabled():
        bucket = _RESOLVED_BUCKETS.get(get_storage_bucket(), get_storage_bucket())
        supabase_url = get_supabase_url()
        encoded = "/".join(quote(p) for p in clean.split('/'))
        return f"{supabase_url}/storage/v1/object/public/{bucket}/{encoded}"

    # 3. Local relative path (e.g. 'uploads/organizer_qrs/...', '/static/...', or 'static/...')
    clean_local = clean.replace('static/', '').lstrip('/')
    if not clean_local.startswith('uploads/'):
        clean_local = f"uploads/{clean_local}"

    # Check local filesystem existence
    try:
        if current_app:
            local_file = Path(current_app.root_path) / 'static' / clean_local
        else:
            local_file = Path(__file__).resolve().parent.parent / 'static' / clean_local

        if local_file.exists() and local_file.is_file():
            try:
                return url_for('static', filename=clean_local)
            except Exception:
                return f"/static/{clean_local}"
    except Exception:
        pass

    # 4. If missing from local disk, check if it can be resolved via Supabase Storage
    # (e.g., an old record 'uploads/organizer_qrs/xyz.jpg' where file is in Supabase 'organizer_qrs/xyz.jpg')
    if is_cloud_storage_enabled():
        bucket = _RESOLVED_BUCKETS.get(get_storage_bucket(), get_storage_bucket())
        supabase_url = get_supabase_url()
        stripped = clean_local.replace('uploads/', '')
        encoded = "/".join(quote(p) for p in stripped.split('/'))
        cloud_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{encoded}"
        return cloud_url

    # Missing file: return None or default
    return default
