import io
import os
from pathlib import Path
import qrcode
from PIL import Image

def generate_ticket_qr(registration_code, base_url=""):
    """
    Generates a high-quality QR code for the given registration code.
    In cloud/production environments, uploads directly to Supabase Storage.
    In local development, saves to static/uploads/qrcodes/ with local fallback.
    """
    upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'qrcodes'
    upload_dir.mkdir(parents=True, exist_ok=True)

    # QR payload can be scanned by organizer camera
    qr_payload = f"CAMPUSFLOW-TICKET:{registration_code}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff").convert('RGB')
    filename = f"qr_{registration_code}.png"

    # Save to memory buffer for persistent cloud upload
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    try:
        from services.storage_service import upload_file, is_cloud_storage_enabled
        if is_cloud_storage_enabled():
            success, public_url, storage_path = upload_file(
                buffer.getvalue(),
                folder="qrcodes",
                filename=filename,
                content_type="image/png"
            )
            if success and public_url:
                return public_url
    except Exception:
        pass

    # Save to local filesystem as fallback
    file_path = upload_dir / filename
    img.save(file_path, "PNG")

    return f"uploads/qrcodes/{filename}"
