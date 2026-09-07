#!/usr/bin/env python3
"""
Campus Flow SQLite to Microsoft SQL Server (SSMS) Data Migration Tool
====================================================================
Safely transfers existing application data from SQLite (campus_flow.db / backup.db)
to Microsoft SQL Server (SSMS) without modifying or corrupting the source database.

Usage:
  python migrate_sqlite_to_mssql.py [--sqlite-path campus_flow.db] [--mssql-url URL] [--dry-run]
"""

import os
import sys
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

# Ordered list of tables to respect foreign key constraints
TABLE_ORDER = [
    'users',
    'student_profiles',
    'organizer_profiles',
    'faculty_profiles',
    'events',
    'custom_registration_fields',
    'event_registrations',
    'custom_field_responses',
    'payments',
    'attendance_records',
    'announcements',
    'certificates'
]

# Explicit column mappings for each table
TABLE_COLUMNS = {
    'users': [
        'id', 'email', 'password_hash', 'name', 'phone', 'role',
        'is_active', 'created_at', 'updated_at'
    ],
    'student_profiles': [
        'id', 'user_id', 'roll_number', 'department', 'year',
        'section', 'college_id_card'
    ],
    'organizer_profiles': [
        'id', 'user_id', 'organization_name', 'department', 'designation',
        'is_verified', 'status', 'rejection_reason', 'approved_by_id', 'approved_at'
    ],
    'faculty_profiles': [
        'id', 'user_id', 'department', 'employee_id', 'designation'
    ],
    'events': [
        'id', 'title', 'slug', 'organizer_id', 'event_type', 'department',
        'faculty_coordinator', 'faculty_coordinator_contact', 'contact_info',
        'allowed_departments', 'allowed_years', 'allowed_sections', 'eligibility_notes',
        'description', 'rules', 'poster_image', 'venue', 'start_time', 'end_time',
        'registration_deadline', 'max_participants', 'registration_fee', 'is_free',
        'status', 'rejection_reason', 'created_at', 'updated_at'
    ],
    'custom_registration_fields': [
        'id', 'event_id', 'field_label', 'field_name', 'field_type',
        'is_required', 'placeholder', 'options', 'display_order'
    ],
    'event_registrations': [
        'id', 'event_id', 'student_id', 'registration_code', 'qr_code_image',
        'status', 'created_at'
    ],
    'custom_field_responses': [
        'id', 'registration_id', 'field_id', 'field_value'
    ],
    'payments': [
        'id', 'registration_id', 'event_id', 'student_id', 'organizer_id',
        'amount', 'expected_amount', 'detected_amount', 'currency', 'transaction_id',
        'status', 'payment_method', 'payment_screenshot', 'screenshot_hash',
        'fraud_risk', 'fraud_details', 'ocr_extracted_data', 'verification_reason',
        'notes', 'submitted_at', 'verified_at', 'verified_by_id', 'created_at', 'updated_at'
    ],
    'attendance_records': [
        'id', 'registration_id', 'event_id', 'student_id', 'marked_by_id',
        'scanned_at', 'verification_method', 'remarks'
    ],
    'announcements': [
        'id', 'event_id', 'author_id', 'title', 'message', 'is_pinned', 'created_at'
    ],
    'certificates': [
        'id', 'event_id', 'student_id', 'registration_id', 'certificate_code',
        'roll_number', 'file_path', 'original_filename', 'file_type', 'extracted_text',
        'status', 'assigned_by_id', 'upload_date', 'created_at', 'updated_at'
    ]
}


def ensure_mssql_schema(mssql_url: str):
    """Initializes SQLAlchemy tables on SQL Server if they do not exist."""
    print("Ensuring target Microsoft SQL Server schema tables exist...")
    from app import create_app
    from models import db
    
    app = create_app()
    with app.app_context():
        db.create_all()
    print("[+] SQL Server tables verified successfully.")


def migrate_data(sqlite_path: Path, mssql_url: str, dry_run: bool = False):
    print("=" * 65)
    print("CAMPUS FLOW: SQLite -> Microsoft SQL Server (SSMS) Migration")
    print("=" * 65)
    print(f"Source SQLite DB: {sqlite_path.resolve()}")
    print(f"Target Database:  SQL Server [campus_flow]")
    print(f"Mode:             {'DRY RUN (Inspection Only)' if dry_run else 'LIVE MIGRATION'}")
    print("-" * 65)

    if not sqlite_path.exists():
        print(f"Error: Source SQLite database not found at {sqlite_path}")
        sys.exit(1)

    # 1. Connect to SQLite
    sqlite_conn = sqlite3.connect(str(sqlite_path))
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cur = sqlite_conn.cursor()

    mssql_conn = None
    mssql_cur = None

    if not dry_run:
        # First ensure tables exist in SQL Server
        ensure_mssql_schema(mssql_url)
        
        import pyodbc
        conn_str = (
            "Driver={ODBC Driver 18 for SQL Server};"
            "Server=localhost;"
            "Database=campus_flow;"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )
        try:
            mssql_conn = pyodbc.connect(conn_str, autocommit=False)
            mssql_cur = mssql_conn.cursor()
            print("[+] Successfully connected to Microsoft SQL Server via pyodbc.")
        except Exception as e:
            print(f"[!] Direct pyodbc connection failed: {e}")
            print("Attempting connection with ODBC Driver 17 for SQL Server...")
            try:
                conn_str17 = conn_str.replace("ODBC Driver 18", "ODBC Driver 17")
                mssql_conn = pyodbc.connect(conn_str17, autocommit=False)
                mssql_cur = mssql_conn.cursor()
                print("[+] Connected using ODBC Driver 17.")
            except Exception as e17:
                print(f"[!] Could not connect to SQL Server: {e17}")
                sys.exit(1)

    table_stats = {}
    total_migrated_records = 0

    try:
        for table_name in TABLE_ORDER:
            # Check if table exists in SQLite
            sqlite_cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            )
            if not sqlite_cur.fetchone():
                print(f"[-] Table '{table_name}' does not exist in SQLite DB. Skipping.")
                continue

            # Read all rows from SQLite
            sqlite_cur.execute(f"SELECT * FROM {table_name}")
            rows = sqlite_cur.fetchall()
            row_count = len(rows)

            if row_count == 0:
                print(f"[*] Table '{table_name}': 0 records found. Skipped.")
                table_stats[table_name] = 0
                continue

            defined_cols = TABLE_COLUMNS.get(table_name, [])

            if dry_run:
                print(f"[DRY-RUN] Table '{table_name}': {row_count} records ready for migration.")
                table_stats[table_name] = row_count
                total_migrated_records += row_count
                continue

            # Check if table already has rows in SQL Server
            mssql_cur.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            existing_count = mssql_cur.fetchone()[0]
            if existing_count > 0:
                print(f"[!] Table '{table_name}' already contains {existing_count} records in SQL Server. Skipping to avoid duplicate keys.")
                table_stats[table_name] = f"Skipped ({existing_count} already exist)"
                continue

            # Enable IDENTITY_INSERT to preserve original primary key IDs
            mssql_cur.execute(f"SET IDENTITY_INSERT [{table_name}] ON")

            # Inspect available columns from SQLite row keys
            sample_row_keys = set(rows[0].keys())
            active_cols = [c for c in defined_cols if c in sample_row_keys]

            cols_formatted = ", ".join([f"[{c}]" for c in active_cols])
            placeholders = ", ".join(["?" for _ in active_cols])
            insert_sql = f"INSERT INTO [{table_name}] ({cols_formatted}) VALUES ({placeholders})"

            migrated_this_table = 0
            for row in rows:
                values = []
                for col in active_cols:
                    val = row[col]
                    # Parse boolean strings or integers if needed
                    if col in ('is_active', 'is_verified', 'is_free', 'is_required', 'is_pinned'):
                        if val is not None:
                            val = 1 if (val == 1 or val is True or str(val).lower() == 'true') else 0
                    # Parse datetime strings
                    elif 'created_at' in col or 'updated_at' in col or 'start_time' in col or 'end_time' in col or 'registration_deadline' in col or 'scanned_at' in col or 'upload_date' in col or 'approved_at' in col:
                        if val and isinstance(val, str):
                            try:
                                # SQLite standard ISO strings: YYYY-MM-DD HH:MM:SS.ffffff
                                val = datetime.fromisoformat(val.replace("Z", "+00:00"))
                            except ValueError:
                                try:
                                    val = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                                except Exception:
                                    pass
                    values.append(val)

                mssql_cur.execute(insert_sql, tuple(values))
                migrated_this_table += 1

            # Disable IDENTITY_INSERT
            mssql_cur.execute(f"SET IDENTITY_INSERT [{table_name}] OFF")
            mssql_conn.commit()

            print(f"[+] Table '{table_name}': Successfully migrated {migrated_this_table}/{row_count} records.")
            table_stats[table_name] = migrated_this_table
            total_migrated_records += migrated_this_table

        if not dry_run:
            print("-" * 65)
            print(f"MIGRATION COMPLETE! Total records transferred: {total_migrated_records}")
            print("=" * 65)
            for tbl, cnt in table_stats.items():
                print(f"  - {tbl:<30} : {cnt}")
            print("=" * 65)
        else:
            print("-" * 65)
            print(f"DRY RUN SUMMARY: {total_migrated_records} valid records found across all Campus Flow tables.")

    except Exception as err:
        if mssql_conn and not dry_run:
            mssql_conn.rollback()
        print(f"\n[!] Migration Error: {err}")
        raise err
    finally:
        sqlite_conn.close()
        if mssql_conn:
            mssql_conn.close()

    return table_stats


def main():
    parser = argparse.ArgumentParser(description="Campus Flow SQLite to Microsoft SQL Server Data Migration Tool")
    parser.add_argument(
        "--sqlite-path",
        default=str(BASE_DIR / "campus_flow.db"),
        help="Path to SQLite db file (default: campus_flow.db)"
    )
    parser.add_argument(
        "--mssql-url",
        default=os.environ.get("DATABASE_URL"),
        help="SQL Server Connection URL (default: reads DATABASE_URL from .env)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the migration without writing changes to SQL Server"
    )

    args = parser.parse_args()
    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.exists():
        # check fallback fastfest.db
        if (BASE_DIR / "fastfest.db").exists():
            sqlite_path = BASE_DIR / "fastfest.db"

    migrate_data(sqlite_path, args.mssql_url or "SQL Server Target", dry_run=args.dry_run)


if __name__ == "__main__":
    main()
