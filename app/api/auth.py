"""
JARVIS Cloud — API Authentication

Provides a decorator that protects endpoints with API key auth.
Clients must send the key in the `X-API-Key` header.

Usage:
    from app.api.auth import require_api_key

    @app.route("/secret")
    @require_api_key
    def secret():
        return {"ok": True}
"""

from functools import wraps
from flask import request, jsonify

from app.config import get_config


def require_api_key(f):
    """
    Flask decorator: rejects requests missing or providing wrong X-API-Key.

    Returns 401 Unauthorized if the key is missing or invalid.
    Uses constant-time comparison to prevent timing attacks.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        cfg = get_config()
        provided_key = request.headers.get("X-API-Key", "")
        expected_key = cfg.jarvis_api_key

        # Constant-time comparison prevents timing-based key guessing.
        # `secrets.compare_digest` is the safe way to compare secrets.
        import secrets
        if not provided_key or not secrets.compare_digest(provided_key, expected_key):
            return jsonify({
                "error": "Unauthorized",
                "message": "Valid X-API-Key header required.",
            }), 401

        return f(*args, **kwargs)

    return decorated
