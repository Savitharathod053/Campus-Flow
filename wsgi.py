"""
Campus Flow - Production WSGI Entry Point
"""

import os
from app import create_app

app = create_app()

# Ensure schema synchronization and baseline initialization on worker process startup
with app.app_context():
    try:
        from services.db_init import ensure_db_initialized
        ensure_db_initialized(app)
    except Exception as e:
        app.logger.warning(f"WSGI startup db initialization note: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
