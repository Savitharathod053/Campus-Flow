"""
Campus Flow - Database Diagnostic Service
Safely inspects the connected SQL Server database and schema status
WITHOUT exposing database credentials or passwords.
"""

import logging
from sqlalchemy import text, inspect
from models import db

logger = logging.getLogger("CampusFlow.DBDiagnostic")

CAMPUS_FLOW_TABLES = [
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
    'attendance_sessions',
    'announcements',
    'certificates',
    'teams',
    'team_members',
    'team_invitations',
    'departments',
    'audit_logs'
]

def get_safe_db_info():
    """
    Returns a dictionary containing safe database details:
    dialect, server, database name, current schema, table status.
    Credentials (username, password) are strictly omitted.
    """
    engine = db.engine
    dialect = engine.dialect.name
    
    # Safe server/host extraction (no passwords)
    url = engine.url
    safe_host = url.host or 'localhost'
    safe_db_name = url.database or 'unknown'
    
    current_db_actual = safe_db_name
    current_schema = 'dbo'
    table_status = {}
    db_connected = False
    error_msg = None

    try:
        with engine.connect() as conn:
            db_connected = True
            
            # For SQL Server, get real current DB and schema from server
            if dialect == 'mssql':
                try:
                    res = conn.execute(text("SELECT DB_NAME(), SCHEMA_NAME()")).fetchone()
                    if res:
                        current_db_actual = res[0]
                        current_schema = res[1] or 'dbo'
                except Exception as e:
                    logger.warning(f"Could not query DB_NAME()/SCHEMA_NAME(): {e}")
            elif dialect == 'sqlite':
                current_schema = 'main'

            # Inspect tables
            inspector = inspect(engine)
            existing_tables = set(inspector.get_table_names())

            for table in CAMPUS_FLOW_TABLES:
                exists = table in existing_tables
                row_count = None
                if exists:
                    try:
                        count_res = conn.execute(text(f"SELECT COUNT(*) FROM [{table}]" if dialect == 'mssql' else f"SELECT COUNT(*) FROM {table}")).scalar()
                        row_count = count_res
                    except Exception:
                        row_count = 'N/A'
                table_status[table] = {
                    'exists': exists,
                    'row_count': row_count
                }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Diagnostic connection failed: {error_msg}")

    return {
        'connected': db_connected,
        'dialect': dialect,
        'server': safe_host,
        'database': current_db_actual,
        'schema': current_schema,
        'users_table_exists': table_status.get('users', {}).get('exists', False),
        'tables': table_status,
        'error': error_msg
    }


def run_db_diagnostic(app=None):
    """
    Prints a clean, formatted database diagnostic report to stdout.
    """
    info = get_safe_db_info()
    
    print("=" * 65)
    print("        CAMPUS FLOW - DATABASE DIAGNOSTIC REPORT")
    print("=" * 65)
    print(f"Dialect:          {info['dialect']}")
    print(f"Server / Host:    {info['server']}")
    print(f"Database Name:    {info['database']}")
    print(f"Default Schema:   {info['schema']}")
    print(f"Connected:        {'YES (Active)' if info['connected'] else 'NO (Failed)'}")
    
    if info['error']:
        print(f"Connection Error: {info['error']}")
        print("=" * 65)
        return info

    print("-" * 65)
    print("CAMPUS FLOW TABLES STATUS:")
    all_present = True
    for table, status in info['tables'].items():
        if status['exists']:
            count_str = f"Rows: {status['row_count']}" if status['row_count'] is not None else ""
            print(f"  [OK]    {table:<28} {count_str}")
        else:
            all_present = False
            print(f"  [MISS]  {table:<28} (TABLE MISSING)")

    print("-" * 65)
    print(f"Users Table Present: {'YES' if info['users_table_exists'] else 'NO (CRITICAL ERROR)'}")
    print(f"Overall Health:      {f'ALL {len(CAMPUS_FLOW_TABLES)} TABLES PRESENT - HEALTHY' if all_present else 'INCOMPLETE SCHEMA'}")
    print("=" * 65)
    return info
