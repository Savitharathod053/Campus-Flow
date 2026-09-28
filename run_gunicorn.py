"""
Campus Flow - Production Gunicorn Runner
Dynamically reads PORT from environment without relying on shell variable expansion,
and launches Gunicorn with production concurrency settings.
"""

import os
import sys

def main():
    port = os.environ.get("PORT", "8080").strip() or "8080"
    bind_addr = f"0.0.0.0:{port}"
    print(f"[Campus Flow] Launching Gunicorn on {bind_addr} (PORT={port})...", flush=True)

    args = [
        "gunicorn",
        "wsgi:app",
        "--bind", bind_addr,
        "--workers", "1",
        "--threads", "2",
        "--timeout", "120",
        "--access-logfile", "-",
        "--error-logfile", "-"
    ]

    # Replace current process with gunicorn
    os.execvp("gunicorn", args)

if __name__ == "__main__":
    main()
