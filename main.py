"""
Campus Flow - Production Entry Point Alias (main:app)
Ensures seamless compatibility for deployment environments targeting either 'main:app' or 'wsgi:app'.
"""

import os
from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
