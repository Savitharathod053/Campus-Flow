"""
Campus Flow - Production WSGI Entry Point
Directly imports the single pre-configured application instance to ensure instant,
sub-second worker boots and immediate port binding on Render.
"""

import os
import sys
import traceback

# 1. Startup Diagnostics & Dynamic Port Logging
port = os.environ.get("PORT", "10000")
print("[Campus Flow] Starting application", flush=True)
print(f"[Campus Flow] PORT={port}", flush=True)

# 2. Safe WSGI Application Loading with Traceback Logging
try:
    from app import app
    print("[Campus Flow] WSGI application loaded", flush=True)
except Exception as exc:
    print(f"[Campus Flow] CRITICAL: Failed to load WSGI application: {exc}", file=sys.stderr, flush=True)
    traceback.print_exc()
    raise exc

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(port))
