import os
from pathlib import Path
import qrcode
from PIL import Image, ImageDraw

def generate_ticket_qr(registration_code, base_url=""):
    """
    Generates a high-quality QR code for the given registration code.
    Saves it in static/uploads/qrcodes/ and returns relative path.
    """
    upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'qrcodes'
    upload_dir.mkdir(parents=True, exist_ok=True)

    # QR payload can be scanned by organizer camera
    qr_payload = f"FASTFEST-TICKET:{registration_code}"

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff").convert('RGB')
    
    # Save image
    filename = f"qr_{registration_code}.png"
    file_path = upload_dir / filename
    img.save(file_path, "PNG")

    return f"uploads/qrcodes/{filename}"
