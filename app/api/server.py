"""
JARVIS Cloud — Flask Application Factory

Creates and configures the Flask app. Uses the factory pattern so the
app can be instantiated multiple times with different configs (useful
for testing) and so initialization is explicit.
"""

import logging
from datetime import datetime, timezone
from flask import Flask, jsonify
from flask_cors import CORS

from app.config import get_config
from app.api.auth import require_api_key
from app.logging_config import setup_logging


def create_app() -> Flask:
    """
    Factory function. Builds and returns a configured Flask app.
    """
    cfg = get_config()
    logger = setup_logging()

    app = Flask(__name__)
    app.config["DEBUG"] = cfg.debug

    # Enable CORS so the PWA frontend can call this API from a different origin.
    # In production we'll lock this down to specific origins.
    CORS(app, resources={r"/*": {"origins": "*"}})

    # ====== ROUTES ======

    @app.route("/", methods=["GET"])
    def root():
        """Public root endpoint — basic identification, no auth needed."""
        return jsonify({
            "service": "JARVIS Cloud",
            "version": "0.1.0",
            "status": "operational",
        })

    @app.route("/health", methods=["GET"])
    def health():
        """Public health check — used by Railway and uptime monitors."""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": cfg.environment,
        })

    @app.route("/api/status", methods=["GET"])
    @require_api_key
    def status():
        """
        Authenticated status endpoint.
        Returns config-derived info about this JARVIS instance.
        Requires X-API-Key header.
        """
        return jsonify({
            "owner": cfg.owner_name,
            "title": cfg.owner_title,
            "timezone": cfg.timezone,
            "location": cfg.location_city,
            "environment": cfg.environment,
            "models": {
                "default": cfg.claude_model_default,
                "complex": cfg.claude_model_complex,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ====== ERROR HANDLERS ======

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({
            "error": "Not Found",
            "message": "The requested endpoint does not exist.",
        }), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Internal server error")
        return jsonify({
            "error": "Internal Server Error",
            "message": "Something broke. Check the logs.",
        }), 500

    # ====== REGISTER ADDITIONAL ROUTES ======
    from app.api.dashboard_routes import register_dashboard_routes
    register_dashboard_routes(app)
    from app.api.briefing_routes import register_briefing_routes
    register_briefing_routes(app)
    from app.api.voice_routes import register_voice_routes
    register_voice_routes(app)
    register_chat_routes(app)

    # ====== KOKORO TTS DAEMON ======
    # Starts loading the model asynchronously — Flask is already up and serving
    # by the time the 10-15s model load completes. First TTS request before
    # the daemon is ready falls back to OpenAI TTS or macOS say.
    try:
        from app.voice.kokoro_daemon import get_daemon
        get_daemon().start()
    except Exception as _voice_exc:
        logger.warning("Kokoro daemon start failed (non-fatal): %s", _voice_exc)

    # ====== STARTUP LOG ======
    logger.info("=" * 60)
    logger.info("JARVIS Cloud — Flask API initialized")
    logger.info(f"  Owner:       {cfg.owner_name}")
    logger.info(f"  Environment: {cfg.environment}")
    logger.info(f"  Debug:       {cfg.debug}")
    logger.info(f"  Bind:        {cfg.jarvis_api_host}:{cfg.jarvis_api_port}")
    logger.info("=" * 60)

    return app


def register_chat_routes(app: Flask) -> None:
    """Register Claude-powered chat endpoints."""
    from flask import request
    from app.core.claude import JarvisAI

    # One AI instance per app lifecycle
    ai = JarvisAI()

    @app.route("/api/chat", methods=["POST"])
    @require_api_key
    def chat():
        """
        Main chat endpoint. Accepts a query, routes through 3-layer system.

        Body: {"query": "What time is it?", "context": "optional extra context"}
        Returns: {"response": "...", "layer": 1, "model": "local", "tokens": {...}}
        """
        data = request.get_json(silent=True) or {}
        query = data.get("query", "").strip()

        if not query:
            return jsonify({
                "error": "Bad Request",
                "message": "Field 'query' is required.",
            }), 400

        context = data.get("context")
        result = ai.respond(query, context=context)
        return jsonify(result)

    @app.route("/api/chat/clear", methods=["POST"])
    @require_api_key
    def clear_chat():
        """Clear conversation history."""
        ai.clear_history()
        return jsonify({"message": "Conversation history cleared."})
