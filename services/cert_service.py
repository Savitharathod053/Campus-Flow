from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import qrcode

def generate_certificate_image(student_name, roll_number, department, event_title, event_date_str, certificate_code):
    """
    Generates a high-resolution, certificate of participation using Pillow.
    Includes verification certificate code and QR code.
    """
    upload_dir = Path(__file__).resolve().parent.parent / 'static' / 'uploads' / 'certificates'
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Certificate canvas dimensions (1600x1100 px landscape)
    width, height = 1600, 1100
    img = Image.new('RGB', (width, height), color='#fcfbf7')
    draw = ImageDraw.Draw(img)

    # Border colors
    navy = '#0f172a'
    gold = '#d97706'
    accent_blue = '#2563eb'
    slate_dark = '#334155'
    slate_light = '#64748b'

    # Outer decorative borders
    draw.rectangle([30, 30, width - 30, height - 30], outline=gold, width=4)
    draw.rectangle([45, 45, width - 45, height - 45], outline=navy, width=10)
    draw.rectangle([65, 65, width - 65, height - 65], outline=gold, width=2)

    # Corner decorations
    for corner in [(75, 75), (width - 125, 75), (75, height - 125), (width - 125, height - 125)]:
        draw.rectangle([corner[0], corner[1], corner[0] + 50, corner[1] + 50], outline=gold, width=2)

    # Helper function to load font with fallback
    def get_font(size, bold=False):
        try:
            # Try standard Windows fonts
            if bold:
                return ImageFont.truetype("arialbd.ttf", size)
            return ImageFont.truetype("arial.ttf", size)
        except Exception:
            try:
                if bold:
                    return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
                return ImageFont.truetype("DejaVuSans.ttf", size)
            except Exception:
                return ImageFont.load_default()

    font_college = get_font(32, bold=True)
    font_header = get_font(56, bold=True)
    font_sub = get_font(24)
    font_name = get_font(60, bold=True)
    font_body = get_font(28)
    font_event = get_font(42, bold=True)
    font_meta = get_font(22)
    font_code = get_font(20, bold=True)

    # Top College Header
    college_title = "FASTFEST COLLEGE OF ENGINEERING & TECHNOLOGY"
    draw.text((width / 2, 120), college_title, fill=slate_dark, font=font_college, anchor="mm")
    draw.text((width / 2, 160), "OFFICIAL CAMPUS EVENT PLATFORM", fill=slate_light, font=font_sub, anchor="mm")

    # Main Certificate Title
    draw.text((width / 2, 240), "CERTIFICATE OF PARTICIPATION", fill=navy, font=font_header, anchor="mm")

    # Divider bar
    draw.line([(width / 2 - 250, 285), (width / 2 + 250, 285)], fill=gold, width=4)

    # Presentation text
    draw.text((width / 2, 340), "This is proudly presented to", fill=slate_dark, font=font_body, anchor="mm")

    # Participant Name
    draw.text((width / 2, 420), student_name.upper(), fill=accent_blue, font=font_name, anchor="mm")
    
    # Sub details
    student_meta = f"Roll No: {roll_number}  |  Department: {department}"
    draw.text((width / 2, 480), student_meta, fill=slate_dark, font=font_sub, anchor="mm")

    # Body description
    body_text_1 = "for active participation and successful completion of"
    draw.text((width / 2, 540), body_text_1, fill=slate_dark, font=font_body, anchor="mm")

    # Event Title
    draw.text((width / 2, 610), f"\"{event_title}\"", fill=navy, font=font_event, anchor="mm")

    # Date
    draw.text((width / 2, 675), f"Conducted on {event_date_str}", fill=slate_dark, font=font_body, anchor="mm")

    # Verification QR Code
    qr_data = f"FASTFEST-CERT-VERIFY:{certificate_code}"
    qr = qrcode.QRCode(version=1, box_size=4, border=1)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=navy, back_color='#ffffff').convert('RGB')
    qr_w, qr_h = qr_img.size
    img.paste(qr_img, (120, height - 240))

    # Verification texts
    draw.text((120, height - 260), "Scan to Verify Credential", fill=slate_light, font=font_code)
    draw.text((120 + qr_w + 20, height - 200), f"Certificate ID:\n{certificate_code}", fill=slate_dark, font=font_code)

    # Signatures
    # Coordinator Signature Line
    draw.line([(width - 550, height - 170), (width - 350, height - 170)], fill=slate_dark, width=2)
    draw.text((width - 450, height - 145), "Event Coordinator", fill=slate_dark, font=font_sub, anchor="mm")

    # Principal / Dean Signature Line
    draw.line([(width - 280, height - 170), (width - 100, height - 170)], fill=slate_dark, width=2)
    draw.text((width - 190, height - 145), "Dean / Principal", fill=slate_dark, font=font_sub, anchor="mm")

    # Save
    filename = f"cert_{certificate_code}.png"
    file_path = upload_dir / filename
    img.save(file_path, "PNG", quality=95)

    return f"uploads/certificates/{filename}"
