#!/usr/bin/env python3
"""
Campus Flow - Database Diagnostic CLI
Safely checks SQL Server database connection, active database name,
default schema, and existence of all Campus Flow tables.
"""

from app import create_app
from services.db_diagnostic import run_db_diagnostic

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        run_db_diagnostic(app)
