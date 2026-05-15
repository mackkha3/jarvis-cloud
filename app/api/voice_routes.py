"""
JARVIS Cloud — Voice API Routes

POST /api/voice/speak  — synthesize text to WAV audio
GET  /api/voice/status — daemon state, active backend, latency stats
POST /api/voice/activate — (stub) wake-word activation
"""

import logging
from flask import Flask, jsonify, request, Response

from app.api.auth import require_api_key

logger = logging.getLogger("jarvis.api.voice")


def register_voice_routes(app: Flask) -> None:

    @app.route("/api/voice/speak", methods=["POST"])
    @require_api_key
    def voice_speak():
        """
        Synthesize text to speech. Returns WAV audio.

        Body: {"text": "Hello Boss", "voice": "bm_george"}
        Returns: audio/wav on success, or JSON error.
        """
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        voice = data.get("voice", "bm_george")

        if not text:
            return jsonify({"error": "text is required"}), 400

        if len(text) > 2000:
            return jsonify({"error": "text too long (max 2000 chars)"}), 400

        try:
            from app.voice.tts import speak
            wav_bytes = speak(text, voice=voice)

            if wav_bytes:
                return Response(
                    wav_bytes,
                    mimetype="audio/wav",
                    headers={
                        "Content-Disposition": "inline; filename=jarvis.wav",
                        "Content-Length": str(len(wav_bytes)),
                        "X-TTS-Length": str(len(text)),
                    },
                )

            # macOS say path — audio played locally, nothing to return
            return jsonify({
                "played": True,
                "backend": "say",
                "message": "Audio played locally via macOS say (no WAV bytes to stream)",
            })

        except Exception as exc:
            logger.exception("Voice speak error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/voice/status", methods=["GET"])
    @require_api_key
    def voice_status():
        """
        TTS daemon status — replaces the stub from dashboard_routes.py.
        Returns daemon state, active backend, and rolling latency stats.
        """
        try:
            from app.voice.tts import backend_status
            status = backend_status()
            return jsonify({
                "status": "online" if status["kokoro"]["state"] == "ready" else "degraded",
                "wake_word": "hey_jarvis",
                "tts": "kokoro",
                **status,
            })
        except Exception as exc:
            logger.exception("Voice status error: %s", exc)
            return jsonify({
                "status": "error",
                "error": str(exc),
            }), 500

    @app.route("/api/voice/activate", methods=["POST"])
    @require_api_key
    def voice_activate():
        """
        Voice activation endpoint. Currently warms the Kokoro daemon if not ready.
        Full wake-word flow comes when the voice layer is built.
        """
        try:
            from app.voice.kokoro_daemon import get_daemon
            daemon = get_daemon()
            if not daemon._thread or not daemon._thread.is_alive():
                daemon.start()
                return jsonify({"activated": True, "message": "Daemon started"})

            return jsonify({
                "activated": daemon.is_ready,
                "state": daemon.state,
                "message": "Ready" if daemon.is_ready else f"Daemon {daemon.state}",
            })
        except Exception as exc:
            logger.exception("Voice activate error: %s", exc)
            return jsonify({"activated": False, "error": str(exc)}), 500
