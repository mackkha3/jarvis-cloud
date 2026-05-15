"""
JARVIS Cloud — Briefing API Routes

Registers briefing endpoints on the Flask app.
All endpoints require X-API-Key authentication.
"""

import logging
from flask import Flask, jsonify
from app.api.auth import require_api_key

logger = logging.getLogger("jarvis.api.briefings")


def register_briefing_routes(app: Flask) -> None:
    """Register all briefing-related routes."""

    @app.route("/api/briefings/morning", methods=["GET"])
    @require_api_key
    def morning_briefing():
        """
        Generate and return a morning briefing.
        Pulls live data from Calendar, Tasks, Gmail + Claude synthesis.
        """
        try:
            from app.briefings.morning import generate_morning_briefing
            result = generate_morning_briefing()
            return jsonify(result)
        except Exception as e:
            logger.exception(f"Morning briefing endpoint error: {e}")
            return jsonify({
                "error": "Briefing generation failed",
                "message": str(e),
            }), 500
