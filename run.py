"""
Campus Flow - Local Development & Server Runner
"""

import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0' if (os.environ.get('PORT') or os.environ.get('RENDER') or os.environ.get('FLASK_ENV') == 'production') else '127.0.0.1'
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() in ('true', '1', 't')
    print(f"Starting Campus Flow on http://{host}:{port} (Debug: {debug})...")
    app.run(host=host, port=port, debug=debug)
