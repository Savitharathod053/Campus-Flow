import sys
from app import create_app, db
from services.db_init import sync_missing_columns

print("Running manual column migration check...")
app = create_app()
with app.app_context():
    try:
        sync_missing_columns()
        print("Schema migration completed successfully!")
    except Exception as e:
        print(f"Schema migration failed: {e}", file=sys.stderr)
        raise e

