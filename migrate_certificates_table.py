"""
FastFest - Certificates Table Migration Script
Migrates the certificates table schema to support uploaded certificates,
OCR extracted roll numbers, file paths, statuses, and manual assignment.
"""

from app import create_app
from models import db, Certificate
from sqlalchemy import text

def run_migration():
    app = create_app()
    with app.app_context():
        print("Running certificates table migration...")
        
        # Check database dialect
        engine = db.engine
        dialect_name = engine.dialect.name
        print(f"Active database dialect: {dialect_name}")

        try:
            # Check row count
            count = db.session.query(Certificate).count()
        except Exception:
            count = 0

        print(f"Current certificates in table: {count}")

        # Drop and recreate certificates table to match new Model schema perfectly
        try:
            Certificate.__table__.drop(engine, checkfirst=True)
            print("Dropped old certificates table.")
        except Exception as e:
            print(f"Note during drop: {e}")

        Certificate.__table__.create(engine)
        print("Created new certificates table successfully!")
        
        # Verify new columns
        from sqlalchemy import inspect
        inspector = inspect(engine)
        columns = [c['name'] for c in inspector.get_columns('certificates')]
        print(f"New table columns: {columns}")

if __name__ == '__main__':
    run_migration()
