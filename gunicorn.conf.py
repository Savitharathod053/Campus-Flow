"""
Gunicorn Configuration for Campus Flow Production Deployment
Automatically configures dynamic port binding on 0.0.0.0:$PORT and sets optimal worker/thread concurrency.
"""

import os

# Dynamic port binding for Render and cloud hosting (defaults to 5000 or $PORT)
port = os.environ.get("PORT", "5000")
bind = f"0.0.0.0:{port}"

# Optimal worker concurrency for cloud containers (Render Free/Starter has 512MB RAM)
workers = int(os.environ.get("WEB_CONCURRENCY", 2))
threads = 2
timeout = 120
keepalive = 5

# Production logging to stdout/stderr
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
