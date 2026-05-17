"""
JARVIS Cloud — Voice API Routes

POST /api/voice/speak     — synthesize text to WAV audio
GET  /api/voice/status    — daemon state, active backend, latency stats
POST /api/voice/activate  — warm Kokoro daemon
POST /api/voice/chat      — closed-loop conversation session
GET  /api/voice/audio/<f> — serve generated TTS audio
POST /api/voice/conversation/clear — clear session history
"""

import datetime
import logging
import pathlib
import random
import re
import time
import uuid

from flask import Flask, jsonify, request, Response, send_file

from app.api.auth import require_api_key

logger = logging.getLogger("jarvis.api.voice")

_AUDIO_DIR = pathlib.Path("/tmp/jarvis_audio")

# ====== SESSION STORE ======
_sessions: dict = {}
_CONTEXT_TTL = 120  # seconds — cache Google context per session


def _get_or_create_session(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = {
            "history": [],
            "last_active": 0,
            "greeting_done": False,
            "context": "",
            "context_ts": 0,
        }
    return _sessions[session_id]


def _get_cached_context(session: dict) -> str:
    now = time.time()
    if now - session["context_ts"] < _CONTEXT_TTL and session["context"]:
        return session["context"]
    ctx = _get_jarvis_context()
    session["context"] = ctx
    session["context_ts"] = now
    return ctx


# ====== DISMISSAL DETECTION ======
_DISMISSAL_PHRASES = [
    "thank you", "thanks", "thank you jarvis", "thanks jarvis",
    "that will be all", "that's all", "goodbye", "good night",
    "ok jarvis", "okay jarvis", "ok thank you", "okay thank you",
    "that's it", "i'm good", "im good", "no thanks", "no thank you",
    "bye", "bye jarvis", "dismiss", "stand down", "you're dismissed",
    "youre dismissed", "close", "exit", "stop",
]


def _is_dismissal(text: str) -> bool:
    cleaned = text.lower().strip().rstrip(".,!?")
    return any(cleaned == p or cleaned.startswith(p + " ") for p in _DISMISSAL_PHRASES)


# ====== RESPONSE TEMPLATES ======
_FOLLOW_UPS = [
    "Anything else, {title}?",
    "What else can I do for you, {title}?",
    "Is there anything else?",
    "Shall I do anything else?",
    "What else do you need?",
    "Standing by — anything else?",
    "Done. What's next, {title}?",
]

_DISMISSALS = [
    "Of course, {title}. Standing by.",
    "Understood. I'll be here when you need me.",
    "Right. Standing down.",
    "Noted. Have a good one, {title}.",
    "At your service whenever you're ready.",
]


def _get_follow_up(cfg) -> str:
    return random.choice(_FOLLOW_UPS).format(title=cfg.owner_title)


def _get_dismissal_response(cfg) -> str:
    return random.choice(_DISMISSALS).format(title=cfg.owner_title)


# ====== GREETING LOGIC ======
def _generate_greeting(session: dict, cfg) -> str:
    """Time-aware, gap-aware greeting — no external API calls for instant response."""
    now = datetime.datetime.now()
    hour = now.hour
    gap = time.time() - session["last_active"] if session["last_active"] else 999999

    if gap < 120:
        return f"Yes, {cfg.owner_title}."
    if gap < 3600:
        return f"Welcome back, {cfg.owner_title}. Go ahead."
    if hour < 12:
        return f"Good morning, {cfg.owner_title}. What do you need?"
    if hour < 17:
        return f"Good afternoon, {cfg.owner_title}. What can I do for you?"
    if hour < 21:
        return f"Good evening, {cfg.owner_title}. Go ahead."
    return f"Still at it, {cfg.owner_title}. What do you need?"


# ====== AUDIO HELPER ======
_MAX_TTS_WORDS = 45  # ~5-6 seconds synthesis on CPU


def _generate_audio(text: str) -> str | None:
    """Generate Kokoro TTS audio, truncating to _MAX_TTS_WORDS for latency."""
    try:
        from app.voice.tts import speak

        words = text.split()
        if len(words) > _MAX_TTS_WORDS:
            truncated = " ".join(words[:_MAX_TTS_WORDS])
            # Prefer ending at a sentence boundary at least 60% through the truncated text
            for punct in [". ", "! ", "? "]:
                last = truncated.rfind(punct)
                if last > len(truncated) * 0.6:
                    truncated = truncated[:last + 1]
                    break
            text = truncated

        _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        audio_bytes = speak(text)
        if audio_bytes:
            filename = f"{uuid.uuid4().hex}.wav"
            (_AUDIO_DIR / filename).write_bytes(audio_bytes)
            logger.info("Audio generated: %s (%d words)", filename, len(text.split()))
            return f"/api/voice/audio/{filename}"
    except Exception as e:
        logger.error(f"Audio generation error: {e}")
    return None


# ====== CONTEXT HELPER ======
def _get_jarvis_context() -> str:
    try:
        from app.integrations.google import GoogleCalendar, GoogleTasks, GoogleGmail
        now = datetime.datetime.now()
        parts = [f"Current time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}"]

        cal = GoogleCalendar()
        if cal.available:
            events = cal.get_todays_events()
            if events:
                parts.append("Today's calendar: " + ", ".join(e.get("summary", "Untitled") for e in events[:5]))
            else:
                parts.append("Calendar: No events today")

        tc = GoogleTasks()
        if tc.available:
            tasks = tc.get_tasks()
            if tasks:
                parts.append("Pending tasks: " + ", ".join(t.get("title", "") for t in tasks[:5]))

        gmail = GoogleGmail()
        if gmail.available:
            parts.append(f"Unread emails: {gmail.get_unread_count()}")

        return "\n".join(parts)
    except Exception as e:
        logger.error(f"Context fetch error: {e}")
        return ""


# ====== ROUTE REGISTRATION ======

def register_voice_routes(app: Flask) -> None:

    @app.route("/api/voice/speak", methods=["POST"])
    @require_api_key
    def voice_speak():
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
            return jsonify({"played": True, "backend": "say",
                            "message": "Audio played locally via macOS say"})
        except Exception as exc:
            logger.exception("Voice speak error: %s", exc)
            return jsonify({"error": str(exc)}), 500

    @app.route("/api/voice/status", methods=["GET"])
    @require_api_key
    def voice_status():
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
            return jsonify({"status": "error", "error": str(exc)}), 500

    @app.route("/api/voice/activate", methods=["POST"])
    @require_api_key
    def voice_activate():
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


def register_voice_chat_routes(app: Flask) -> None:
    """Register closed-loop conversation and audio-serving routes."""

    @app.route("/api/voice/chat", methods=["POST"])
    @require_api_key
    def voice_chat():
        from app.config import get_config
        from app.core.claude import JarvisAI

        cfg = get_config()
        data = request.get_json(silent=True) or {}
        user_text = data.get("text", "").strip()
        session_id = data.get("session_id", "default")
        is_greeting = data.get("greeting", False)

        session = _get_or_create_session(session_id)

        # ── CASE 1: First tap — return greeting, no Claude call needed ──
        if is_greeting or (not user_text and not session["greeting_done"]):
            greeting_text = _generate_greeting(session, cfg)
            session["greeting_done"] = True
            session["last_active"] = time.time()
            logger.info(f"Greeting — session:{session_id}")

            audio_url = _generate_audio(greeting_text)
            return jsonify({
                "response": greeting_text,
                "audio_url": audio_url,
                "session_id": session_id,
                "session_active": True,
                "layer": 1,
                "tokens": {"input": 0, "output": 0},
            })

        if not user_text:
            return jsonify({"error": "No text provided"}), 400

        session["last_active"] = time.time()
        logger.info(f"Voice chat — session:{session_id} — '{user_text[:60]}'")

        # ── CASE 2: Dismissal phrase — close session gracefully ──
        if _is_dismissal(user_text):
            farewell = _get_dismissal_response(cfg)
            session["greeting_done"] = False
            session["history"] = []
            audio_url = _generate_audio(farewell)
            return jsonify({
                "response": farewell,
                "audio_url": audio_url,
                "session_id": session_id,
                "session_active": False,
                "layer": 1,
                "tokens": {"input": 0, "output": 0},
            })

        # ── CASE 3: Real question — Claude + follow-up ──
        context = _get_cached_context(session)
        ai = JarvisAI()
        ai._conversation_history = session["history"].copy()
        result = ai.respond(query=user_text, context=context)
        response_text = result.get("response", "")

        session["history"].append({"role": "user", "content": user_text})
        session["history"].append({"role": "assistant", "content": response_text})
        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]

        follow_up = _get_follow_up(cfg)
        full_response = response_text + " " + follow_up

        audio_url = _generate_audio(full_response)

        return jsonify({
            "response": full_response,
            "audio_url": audio_url,
            "session_id": session_id,
            "session_active": True,
            "layer": result.get("layer"),
            "tokens": result.get("tokens", {}),
        })

    @app.route("/api/voice/audio/<filename>", methods=["GET"])
    def voice_audio(filename):
        if not re.match(r"^[a-f0-9]{32}\.wav$", filename):
            return jsonify({"error": "Invalid filename"}), 400
        audio_path = _AUDIO_DIR / filename
        if not audio_path.exists():
            return jsonify({"error": "Audio not found"}), 404
        return send_file(str(audio_path), mimetype="audio/wav")

    @app.route("/api/voice/conversation/clear", methods=["POST"])
    @require_api_key
    def clear_conversation():
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id", "default")
        if session_id in _sessions:
            del _sessions[session_id]
        return jsonify({"cleared": True, "session_id": session_id})
