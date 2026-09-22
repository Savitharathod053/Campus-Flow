"""
Campus Flow - Production WSGI Entry Point
Directly imports the single pre-configured application instance to ensure instant,
sub-second worker boots and immediate port binding on Render.
"""

import os
from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
