"""
JARVIS Cloud — Entry Point

Local dev: python run.py
Production: gunicorn run:app --bind 0.0.0.0:8080 --workers 2 --timeout 120
"""

import os
from app.api.server import create_app
from app.config import get_config

app = create_app()

if __name__ == "__main__":
    cfg = get_config()
    port = int(os.environ.get("PORT", cfg.jarvis_api_port))
    print(f"\nJARVIS Cloud starting on http://0.0.0.0:{port}")
    app.run(
        host=cfg.jarvis_api_host,
        port=port,
        debug=cfg.debug,
    )
