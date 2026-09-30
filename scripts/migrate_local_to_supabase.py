"""
Migration Script: Local Uploads to Supabase Storage
Scans local static/uploads/ directory, uploads all persistent files (certificates, posters, payment proofs)
to the Supabase Storage bucket 'payment-proofs', and updates database records in PostgreSQL
with the permanent Supabase public URLs.
"""

import os
import sys
import mimetypes
from pathlib import Path
from urllib.parse import quote
import requests
from dotenv import load_dotenv

# Ensure app root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

load_dotenv(dotenv_path=root_dir / ".env", override=True)

from app import create_app
from models import db, Certificate, Payment, Event
from services.storage_service import (
    get_supabase_url,
    get_supabase_service_key,
    get_storage_bucket,
    check_bucket_exists
)


def run_migration():
    print("=" * 65)
    print("   CAMPUS FLOW: MIGRATE LOCAL UPLOADS TO SUPABASE STORAGE")
    print("=" * 65)

    supabase_url = get_supabase_url()
    service_key = get_supabase_service_key()
    bucket = get_storage_bucket()

    print(f"Supabase URL:    {supabase_url or '(Not set)'}")
    print(f"Target Bucket:   {bucket}")
    
    if not supabase_url:
        print("[ERROR] SUPABASE_URL is not set in your .env file.")
        sys.exit(1)

    if not service_key or service_key.startswith("sb_publishable_"):
        print("\n[ERROR] SUPABASE_SERVICE_ROLE_KEY is missing or set to a client publishable key.")
        print("To upload files to Supabase Storage, the secret service_role key (starts with 'eyJ...') is required.")
        print("Please update SUPABASE_SERVICE_ROLE_KEY in your local .env file and run this script again.\n")
        sys.exit(1)

    print(f"Service Key:     {service_key[:12]}... (Length: {len(service_key)})")

    # Check bucket in Supabase
    bucket_ok, bucket_err = check_bucket_exists(bucket)
    if not bucket_ok:
        print(f"[ERROR] Could not access bucket '{bucket}': {bucket_err}")
        sys.exit(1)

    print(f"[OK] Supabase Storage bucket '{bucket}' is accessible and verified.\n")

    uploads_dir = root_dir / "static" / "uploads"
    if not uploads_dir.exists():
        print(f"[INFO] No local uploads directory found at: {uploads_dir}")
        sys.exit(0)

    # Collect all files to migrate
    candidate_files = []
    for p in uploads_dir.rglob("*"):
        if p.is_file() and not p.name.startswith("."):
            # Skip test runner temporary files
            rel_str = str(p.relative_to(uploads_dir)).replace("\\", "/")
            if "test_payment_proofs" in rel_str:
                continue
            candidate_files.append((p, rel_str))

    print(f"Found {len(candidate_files)} file(s) in {uploads_dir} to migrate.")
    if not candidate_files:
        print("No files to migrate. Exiting.")
        sys.exit(0)

    app = create_app()
    uploaded_count = 0
    db_updated_count = 0
    failed_count = 0

    with app.app_context():
        headers = {
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "x-upsert": "true"
        }

        for file_path, rel_path in candidate_files:
            # Determine destination folder inside bucket
            # E.g.: certificates/event_177/abc.pdf -> certificates/event_177/abc.pdf
            # E.g.: organizer_qrs/qr.png -> organizer-qrs/qr.png
            # E.g.: payment_proofs/proof.png -> payment-proofs/proof.png
            parts = rel_path.split("/")
            top_folder = parts[0]
            
            if top_folder in ("payment_proofs", "payment_proof"):
                target_folder = "payment-proofs"
            elif top_folder in ("organizer_qrs", "organizer_qr"):
                target_folder = "organizer-qrs"
            elif top_folder in ("event_images", "posters", "events"):
                target_folder = "event-images"
            elif top_folder == "certificates":
                target_folder = "certificates"
            else:
                target_folder = top_folder

            sub_path = "/".join(parts[1:])
            storage_path = f"{target_folder}/{sub_path}" if sub_path else f"{target_folder}/{file_path.name}"

            guessed_type, _ = mimetypes.guess_type(file_path.name)
            content_type = guessed_type or "application/octet-stream"
            headers["Content-Type"] = content_type

            # 1. Read and upload file to Supabase
            try:
                with open(file_path, "rb") as f:
                    file_bytes = f.read()

                upload_endpoint = f"{supabase_url}/storage/v1/object/{bucket}/{storage_path}"
                resp = requests.post(upload_endpoint, headers=headers, data=file_bytes, timeout=30)

                if resp.status_code in (200, 201):
                    encoded_path = "/".join(quote(p) for p in storage_path.split("/"))
                    public_url = f"{supabase_url}/storage/v1/object/public/{bucket}/{encoded_path}"
                    uploaded_count += 1
                    print(f"[UPLOADED] {rel_path} -> {public_url}")

                    # 2. Update matching database records
                    # Check Certificate records
                    certs = Certificate.query.filter(
                        (Certificate.file_path.like(f"%{file_path.name}")) |
                        (Certificate.file_path.like(f"%{rel_path}%"))
                    ).all()
                    for cert in certs:
                        cert.file_path = public_url
                        db_updated_count += 1

                    # Check Payment records
                    payments = Payment.query.filter(
                        (Payment.payment_screenshot.like(f"%{file_path.name}")) |
                        (Payment.payment_screenshot.like(f"%{rel_path}%"))
                    ).all()
                    for pay in payments:
                        pay.payment_screenshot = public_url
                        db_updated_count += 1

                    # Check Event posters & QRs
                    events_poster = Event.query.filter(
                        (Event.poster_image.like(f"%{file_path.name}")) |
                        (Event.poster_image.like(f"%{rel_path}%"))
                    ).all()
                    for ev in events_poster:
                        ev.poster_image = public_url
                        db_updated_count += 1

                    events_qr = Event.query.filter(
                        (Event.upi_qr_image.like(f"%{file_path.name}")) |
                        (Event.upi_qr_image.like(f"%{rel_path}%"))
                    ).all()
                    for ev in events_qr:
                        ev.upi_qr_image = public_url
                        db_updated_count += 1

                else:
                    failed_count += 1
                    print(f"[FAIL] {rel_path} -> HTTP {resp.status_code}: {resp.text}")

            except Exception as e:
                failed_count += 1
                print(f"[ERROR] {rel_path} -> {e}")

        # Commit all updated database records
        db.session.commit()

    print("\n" + "=" * 65)
    print("MIGRATION SUMMARY")
    print(f"Total Candidate Files: {len(candidate_files)}")
    print(f"Files Uploaded:        {uploaded_count}")
    print(f"Database Rows Updated: {db_updated_count}")
    print(f"Failed Uploads:        {failed_count}")
    print("=" * 65)


if __name__ == "__main__":
    run_migration()
