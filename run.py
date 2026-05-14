"""
JARVIS Cloud — Local Development Entry Point

Run this file to start the Flask development server:
    python run.py

For production (Railway), gunicorn imports `app` directly from this module.
"""

from app.api.server import create_app
from app.config import get_config

# Create the app at module level so gunicorn can find it.
app = create_app()


if __name__ == "__main__":
    cfg = get_config()
    print()
    print("=" * 60)
    print(f"JARVIS Cloud starting on http://{cfg.jarvis_api_host}:{cfg.jarvis_api_port}")
    print(f"Local URL:  http://localhost:{cfg.jarvis_api_port}")
    print(f"Press Ctrl+C to stop")
    print("=" * 60)
    print()

    app.run(
        host=cfg.jarvis_api_host,
        port=cfg.jarvis_api_port,
        debug=cfg.debug,
    )
