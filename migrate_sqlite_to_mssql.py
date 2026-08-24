#!/usr/bin/env python3
"""
FastFest SQLite to Microsoft SQL Server (SSMS) Data Migration Tool
==================================================================
Safely transfers existing FastFest application data from SQLite (fastfest.db)
to Microsoft SQL Server (SSMS) without modifying or corrupting the source database.

Usage:
  python migrate_sqlite_to_mssql.py [--sqlite-path fastfest.db] [--mssql-url URL] [--dry-run]
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

# Boolean column names across models for proper type coercion
BOOLEAN_COLUMNS = {
    'is_active', 'is_verified', 'is_free', 'is_required',
    'is_pinned'
}

# Datetime column names across models for proper type coercion
DATETIME_COLUMNS = {
    'created_at', 'updated_at', 'approved_at', 'start_time',
    'end_time', 'registration_deadline', 'scanned_at', 'upload_date', 'issued_at'
}


def parse_datetime(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        formats = [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d"
        ]
        for fmt in formats:
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return val


def parse_boolean(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, int):
        return 1 if val else 0
    if isinstance(val, str):
        return 1 if val.lower() in ('true', '1', 't', 'yes') else 0
    return 1 if val else 0


def ensure_mssql_schema(mssql_url: str):
    """Ensures Microsoft SQL Server tables exist before inserting data."""
    try:
        from app import create_app
        from models import db
        from config import Config
        
        class MigrationConfig(Config):
            SQLALCHEMY_DATABASE_URI = mssql_url
            
        app = create_app(MigrationConfig)
        with app.app_context():
            db.create_all()
        print("  [+] SQL Server schema verified / created successfully.")
    except Exception as e:
        print(f"  [!] Note on schema creation: {e}")


def migrate_data(sqlite_path: Path, mssql_url: str, dry_run: bool = False):
    print("=" * 65)
    print("FASTFEST: SQLite -> Microsoft SQL Server (SSMS) Migration")
    print("=" * 65)
    print(f"Source SQLite DB: {sqlite_path.resolve()}")
    print(f"Target Database:  SQL Server [fastfest]")
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
            "Database=fastfest;"
            "Trusted_Connection=yes;"
            "TrustServerCertificate=yes;"
        )
        try:
            mssql_conn = pyodbc.connect(conn_str, autocommit=False)
            mssql_cur = mssql_conn.cursor()
            mssql_cur.fast_executemany = True
        except Exception as e:
            print(f"\n[!] Failed to connect to SQL Server database: {e}")
            sqlite_conn.close()
            sys.exit(1)

    total_migrated_records = 0
    table_stats = {}

    try:
        # Verify and prepare tables
        for table_name in TABLE_ORDER:
            # Check if table exists in SQLite
            sqlite_cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?;",
                (table_name,)
            )
            if not sqlite_cur.fetchone():
                print(f"  [-] Table '{table_name}' does not exist in SQLite source. Skipping.")
                continue

            # Fetch rows from SQLite
            sqlite_cur.execute(f"SELECT * FROM [{table_name}]")
            rows = sqlite_cur.fetchall()
            row_count = len(rows)

            if row_count == 0:
                print(f"  [.] Table '{table_name}': 0 rows.")
                table_stats[table_name] = 0
                continue

            # Get destination table column names
            # Get destination table column info (name, is_nullable, column_default)
            mssql_cur.execute(
                "SELECT COLUMN_NAME, IS_NULLABLE, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = ?",
                (table_name,)
            )
            target_cols_info = {row[0].lower(): (row[0], row[1], row[2]) for row in mssql_cur.fetchall()}
            target_cols_set = {k: v[0] for k, v in target_cols_info.items()}

            # Column mappings for schema variations
            column_aliases = {
                'certificate_image': 'file_path',
                'issued_at': 'upload_date'
            }

            # Map sqlite rows to target table schema
            source_cols = [col[0] for col in sqlite_cur.description]
            
            # Determine valid columns for insert
            valid_insert_cols = []
            mapped_target_lower = set()
            for col in source_cols:
                mapped_col = column_aliases.get(col, col)
                if mapped_col.lower() in target_cols_set:
                    valid_insert_cols.append((col, target_cols_set[mapped_col.lower()]))
                    mapped_target_lower.add(mapped_col.lower())

            # Extra required defaults if not present in source SQLite table
            extra_defaults = {}
            if table_name == 'certificates':
                if 'original_filename' not in mapped_target_lower:
                    extra_defaults['original_filename'] = 'certificate.pdf'
                if 'file_type' not in mapped_target_lower:
                    extra_defaults['file_type'] = 'pdf'
                if 'status' not in mapped_target_lower:
                    extra_defaults['status'] = 'MATCHED'
                if 'upload_date' not in mapped_target_lower:
                    extra_defaults['upload_date'] = datetime.utcnow()
                if 'created_at' not in mapped_target_lower:
                    extra_defaults['created_at'] = datetime.utcnow()
                if 'updated_at' not in mapped_target_lower:
                    extra_defaults['updated_at'] = datetime.utcnow()

            all_insert_target_cols = [c[1] for c in valid_insert_cols] + list(extra_defaults.keys())
            cols_str = ", ".join(f'[{c}]' for c in all_insert_target_cols)
            placeholders = ", ".join(["?"] * len(all_insert_target_cols))

            # Transform row data for SQL Server compatibility
            transformed_rows = []
            for row in rows:
                row_dict = dict(row)
                transformed_values = []
                for src_col, tgt_col in valid_insert_cols:
                    val = row_dict[src_col]
                    if tgt_col.lower() in BOOLEAN_COLUMNS or src_col.lower() in BOOLEAN_COLUMNS:
                        val = parse_boolean(val)
                    elif tgt_col.lower() in DATETIME_COLUMNS or src_col.lower() in DATETIME_COLUMNS:
                        val = parse_datetime(val)
                    transformed_values.append(val)
                for ext_k, ext_v in extra_defaults.items():
                    if ext_k == 'original_filename' and 'certificate_image' in row_dict:
                        img_path = row_dict.get('certificate_image') or 'cert.pdf'
                        ext_v = Path(img_path).name
                    transformed_values.append(ext_v)
                transformed_rows.append(tuple(transformed_values))

            if dry_run:
                print(f"  [+] [DRY-RUN] Table '{table_name}': {row_count} rows verified and ready for transfer.")
                table_stats[table_name] = row_count
                total_migrated_records += row_count
                continue

            # Live Migration: Insert into SQL Server with IDENTITY_INSERT handling
            has_id = any(c[1].lower() == 'id' for c in valid_insert_cols)
            if has_id:
                try:
                    mssql_cur.execute(f"SET IDENTITY_INSERT [{table_name}] ON;")
                except Exception:
                    pass

            insert_query = f"INSERT INTO [{table_name}] ({cols_str}) VALUES ({placeholders})"
            
            for trow in transformed_rows:
                try:
                    mssql_cur.execute(insert_query, trow)
                except Exception as ex:
                    # Ignore duplicate key error (2627 / 2601) for idempotent execution
                    if '2627' in str(ex) or '2601' in str(ex):
                        continue
                    else:
                        raise ex

            if has_id:
                try:
                    mssql_cur.execute(f"SET IDENTITY_INSERT [{table_name}] OFF;")
                except Exception:
                    pass

            print(f"  [+] Table '{table_name}': {row_count} rows successfully migrated.")
            table_stats[table_name] = row_count
            total_migrated_records += row_count

        if not dry_run:
            mssql_conn.commit()
            print("-" * 65)
            print(f"SUCCESS: Total records migrated to SQL Server: {total_migrated_records}")
        else:
            print("-" * 65)
            print(f"DRY RUN SUMMARY: {total_migrated_records} valid records found across all FastFest tables.")

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
    parser = argparse.ArgumentParser(description="FastFest SQLite to Microsoft SQL Server Data Migration Tool")
    parser.add_argument(
        "--sqlite-path",
        default=str(BASE_DIR / "fastfest.db"),
        help="Path to existing SQLite fastfest.db file (default: fastfest.db)"
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

    migrate_data(sqlite_path, args.mssql_url or "SQL Server Target", dry_run=args.dry_run)


if __name__ == "__main__":
    main()
