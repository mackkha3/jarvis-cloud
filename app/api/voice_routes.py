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
import json
import logging
import pathlib
import random
import re
import time
import urllib.request
import uuid

import pytz

from flask import Flask, jsonify, request, Response, send_file

from app.api.auth import require_api_key

logger = logging.getLogger("jarvis.api.voice")

_AUDIO_DIR = pathlib.Path("/tmp/jarvis_audio")

# ====== SESSION STORE ======
_sessions: dict = {}
_CONTEXT_TTL = 120  # seconds — cache Google context per session

# GPS location for this JARVIS instance — updated by POST /api/location
_location_store: dict = {"lat": None, "lon": None}


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


def _is_mid_task(response_text: str) -> bool:
    """Detect if JARVIS is mid-task — suppress follow-up prompt."""
    text = response_text.lower().strip()
    if text.endswith('?'):
        return True
    mid_task_phrases = [
        'what should i call', 'what date', 'what time', 'how long',
        'what would you like', 'could you provide', 'tell me more',
        'what title', 'what name', 'can you give me', 'please provide',
        'which day', 'what day', 'any other details',
    ]
    return any(phrase in text for phrase in mid_task_phrases)


def _get_follow_up(cfg) -> str:
    return random.choice(_FOLLOW_UPS).format(title=cfg.owner_title)


def _get_dismissal_response(cfg) -> str:
    return random.choice(_DISMISSALS).format(title=cfg.owner_title)


# ====== GREETING LOGIC ======
def _generate_greeting(session: dict, cfg) -> str:
    """Time-aware, gap-aware greeting — no external API calls for instant response."""
    now = datetime.datetime.now(pytz.timezone("America/Chicago"))
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
_MAX_TTS_WORDS_DEFAULT = 45   # ~5-6 seconds synthesis on CPU
_MAX_TTS_WORDS_BRIEFING = 250  # briefings / summaries can be longer

_BRIEFING_KEYWORDS = {
    "briefing", "morning briefing", "evening briefing",
    "evening debrief", "debrief", "summary of my day",
    "day summary", "daily summary", "brief me",
    "what's on my", "whats on my", "schedule for today",
    "schedule for tomorrow", "what do i have", "calendar today",
    "calendar tomorrow", "tasks for today", "tasks for tomorrow",
}


def _is_briefing_request(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _BRIEFING_KEYWORDS)


def _generate_audio(text: str, is_briefing: bool = False) -> str | None:
    """Generate Kokoro TTS audio, truncating based on content type for latency."""
    try:
        from app.voice.tts import speak

        limit = _MAX_TTS_WORDS_BRIEFING if is_briefing else _MAX_TTS_WORDS_DEFAULT
        words = text.split()
        if len(words) > limit:
            truncated = " ".join(words[:limit])
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


# ====== WEATHER HELPER ======
def get_weather(lat=None, lon=None, city=None):
    """Fetch current conditions from OpenWeatherMap.

    Returns (weather_text, location_name) or (None, None) on any failure.
    Prefers lat/lon when available; falls back to city name or config coords.
    """
    from app.config import get_config
    cfg = get_config()
    api_key = cfg.openweather_api_key
    if not api_key:
        return None, None

    try:
        if lat is not None and lon is not None:
            url = (f"https://api.openweathermap.org/data/2.5/weather"
                   f"?lat={lat}&lon={lon}&appid={api_key}&units=imperial")
        elif city:
            url = (f"https://api.openweathermap.org/data/2.5/weather"
                   f"?q={city}&appid={api_key}&units=imperial")
        elif cfg.location_lat and cfg.location_lon:
            url = (f"https://api.openweathermap.org/data/2.5/weather"
                   f"?lat={cfg.location_lat}&lon={cfg.location_lon}&appid={api_key}&units=imperial")
        else:
            return None, None

        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())

        location_name = data.get("name") or city or cfg.location_city or ""
        temp = data["main"]["temp"]
        desc = data["weather"][0]["description"]
        humidity = data["main"]["humidity"]
        return f"{temp:.0f}°F, {desc}, humidity {humidity}%", location_name

    except Exception as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return None, None


# ====== CONTEXT HELPER ======
def _get_jarvis_context() -> str:
    try:
        from app.config import get_config
        from app.integrations.google import GoogleCalendar, GoogleTasks, GoogleGmail
        cfg = get_config()
        now = datetime.datetime.now(pytz.timezone("America/Chicago"))
        parts = [f"Current time: {now.strftime('%A, %B %d, %Y at %I:%M %p')}"]

        # Weather — use GPS coords if available, fall back to config city
        lat = _location_store.get("lat")
        lon = _location_store.get("lon")
        weather_text, location_name = get_weather(
            lat=lat, lon=lon, city=cfg.location_city or None
        )
        if location_name:
            parts.append(f"User location: {location_name}")
        if weather_text:
            parts.append(f"Current weather: {weather_text}")

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

    @app.route("/api/voice/tts-mode", methods=["GET"])
    @require_api_key
    def get_tts_mode():
        """Return current server TTS mode so frontend knows whether to use browser TTS."""
        from app.config import get_config
        cfg = get_config()
        return jsonify({"mode": cfg.tts_mode})


def register_voice_chat_routes(app: Flask) -> None:
    """Register closed-loop conversation and audio-serving routes."""

    @app.route("/api/location", methods=["POST"])
    @require_api_key
    def set_location():
        """Store GPS coordinates from the browser. Expires all context caches so the
        next voice/chat request re-fetches weather with the actual GPS position."""
        data = request.get_json(silent=True) or {}
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is not None and lon is not None:
            _location_store["lat"] = float(lat)
            _location_store["lon"] = float(lon)
            # Expire cached context so next chat request includes GPS-based weather
            for s in _sessions.values():
                s["context_ts"] = 0
            logger.info("GPS location updated: %.4f, %.4f", lat, lon)
        return jsonify({"status": "ok"})

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

        # Accept lat/lon in body as a fallback update (e.g. if /api/location fired first)
        body_lat = data.get("lat")
        body_lon = data.get("lon")
        if body_lat is not None and body_lon is not None and _location_store["lat"] is None:
            _location_store["lat"] = float(body_lat)
            _location_store["lon"] = float(body_lon)
            logger.info("GPS location set from chat body: %.4f, %.4f", body_lat, body_lon)

        session = _get_or_create_session(session_id)

        # ── CASE 1: First tap — return greeting, no Claude call needed ──
        if is_greeting or (not user_text and not session["greeting_done"]):
            # Server-side dedup: ignore duplicate greeting within 3 seconds
            import time
            now = time.time()
            last_greeting = session.get("last_greeting_ts", 0)
            if now - last_greeting < 3.0:
                # Duplicate greeting request — return same response silently
                return jsonify({"response": "", "audio_url": None, "layer": 0})
            session["last_greeting_ts"] = now
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

        # ── Parse and execute <action> tags from Claude's response ──
        action_match = re.search(r'<action>(.*?)</action>', response_text, re.DOTALL)
        action_suffix = ""
        if action_match:
            try:
                action_data = json.loads(action_match.group(1).strip())
                if action_data.get("type") == "create_calendar_event":
                    from app.integrations.google import GoogleCalendar
                    cal = GoogleCalendar()
                    if cal.available:
                        event = cal.create_event(
                            title=action_data.get("title", ""),
                            date=action_data.get("date", ""),
                            time=action_data.get("time", ""),
                            duration_minutes=action_data.get("duration_minutes", 60),
                            description=action_data.get("description", ""),
                        )
                        if not event:
                            action_suffix = " Calendar write failed — check credentials."
                    else:
                        action_suffix = " Calendar not connected."

                elif action_data.get("type") == "create_task":
                    from app.integrations.google import GoogleTasks
                    tasks_client = GoogleTasks()
                    result = tasks_client.create_task(
                        title=action_data.get("title", ""),
                        due_date=action_data.get("due_date"),
                    )
                    if result.get("success"):
                        action_suffix = " Added to your task list."
                    else:
                        action_suffix = f" Task creation failed: {result.get('error', 'unknown error')}."

                elif action_data.get("type") == "complete_task":
                    from app.integrations.google import GoogleTasks
                    tasks_client = GoogleTasks()
                    result = tasks_client.complete_task(action_data.get("title", ""))
                    if result.get("success"):
                        action_suffix = f" Marked '{result['title']}' as complete."
                    elif result.get("error") == "no_match":
                        tasks_client.log_accomplishment(action_data.get("title", ""))
                        action_suffix = " No matching task found — logged it as a completed item."
                    else:
                        action_suffix = f" Couldn't mark that complete: {result.get('error', 'unknown')}."

                elif action_data.get("type") == "log_accomplishment":
                    from app.integrations.google import GoogleTasks
                    tasks_client = GoogleTasks()
                    result = tasks_client.log_accomplishment(action_data.get("text", ""))
                    if result.get("success"):
                        action_suffix = f" Logged at {result['time']}."
                    else:
                        action_suffix = " Couldn't log that."

                elif action_data.get("type") == "schedule_meeting_prep":
                    from app.briefings.meeting_prep import queue_meeting_prep
                    prep_event = {
                        "summary": action_data.get("event_title", "Meeting"),
                        "start_dt": action_data.get("start_dt", ""),
                        "start_time": "",
                        "location": "",
                        "description": "",
                        "attendees": [],
                    }
                    queue_meeting_prep(prep_event)
                    action_suffix = " I'll have a briefing ready for you before the meeting."

            except Exception as _ae:
                logger.warning("Action tag parse error: %s", _ae)
            # Strip action tag from spoken response
            response_text = re.sub(r'\s*<action>.*?</action>\s*', ' ', response_text, flags=re.DOTALL).strip()

        if action_suffix:
            response_text += action_suffix

        session["history"].append({"role": "user", "content": user_text})
        session["history"].append({"role": "assistant", "content": response_text})
        if len(session["history"]) > 20:
            session["history"] = session["history"][-20:]

        if _is_mid_task(response_text):
            full_response = response_text
        else:
            follow_up = _get_follow_up(cfg)
            full_response = response_text + " " + follow_up

        is_briefing = _is_briefing_request(user_text)
        audio_url = _generate_audio(full_response, is_briefing=is_briefing)

        return jsonify({
            "response": full_response,
            "audio_url": audio_url,
            "session_id": session_id,
            "session_active": True,
            "layer": result.get("layer"),
            "tokens": result.get("tokens", {}),
        })

    @app.route("/api/meeting-prep/pending", methods=["GET"])
    @require_api_key
    def get_pending_meeting_prep():
        from app.briefings.meeting_prep import get_pending_briefing
        briefing = get_pending_briefing()
        if briefing:
            audio_url = _generate_audio(briefing["text"], is_briefing=True)
            briefing["audio_url"] = audio_url
            return jsonify(briefing)
        return jsonify({"type": None})

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
