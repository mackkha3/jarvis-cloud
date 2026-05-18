"""
JARVIS Cloud — TTS Interface

Fallback chain:
  1. Kokoro daemon    — sub-2s, local, requires kokoro + soundfile + numpy
  2. OpenAI TTS API  — ~1s network, requires openai package + OPENAI_API_KEY
  3. macOS say       — instant, macOS only, plays locally (no audio bytes returned)

speak(text) returns WAV bytes for use in HTTP responses.
If only macOS say is available, returns None (audio plays locally, not serializable).
"""

import base64
import json
import logging
import os
import re
import socket
import struct
import time
from typing import Optional

logger = logging.getLogger("jarvis.voice.tts")

_DEFAULT_VOICE = "bm_george"
_active_backend: str = "unknown"


# ── Text cleaning ─────────────────────────────────────────────────────────────
# Ported from old jarvis/voice/voice.py _clean_for_tts()

def _clean(text: str) -> str:
    text = re.sub(r"J\.A\.R\.V\.I\.S\.?", "Jarvis", text)
    text = text.replace("JARVIS", "Jarvis")
    text = text.replace("—", ", ")
    text = re.sub(r"[*_`~#>\[\]()]+", "", text)
    text = re.sub(r"https?://\S+", "link", text)
    text = re.sub(r"[^\x00-\x7F]+", "", text)   # strip non-ASCII / emojis
    return text.strip()


# ── Backend 1: Kokoro daemon ──────────────────────────────────────────────────

def _kokoro(text: str, voice: str) -> Optional[bytes]:
    """
    Call the in-process Kokoro daemon directly (no socket overhead).
    Falls back to socket if called from outside the daemon's process.
    """
    try:
        from app.voice.kokoro_daemon import get_daemon
        daemon = get_daemon()
        if not daemon.is_ready:
            return None

        t0 = time.monotonic()
        result = daemon.synthesize(text, voice)
        if "error" in result:
            logger.warning("Kokoro synthesis error: %s", result["error"])
            return None

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.debug("Kokoro synthesized %d chars in %dms", len(text), elapsed_ms)
        return base64.b64decode(result["audio"])

    except Exception as exc:
        logger.warning("Kokoro backend failed: %s", exc)
        return None


# ── Backend 2: OpenAI TTS ─────────────────────────────────────────────────────

def _openai(text: str) -> Optional[bytes]:
    """
    Synthesize via OpenAI TTS API.
    Requires: pip install openai  and  OPENAI_API_KEY env var.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.audio.speech.create(
            model="tts-1",
            voice="onyx",
            input=text,
            response_format="wav",
        )
        logger.debug("OpenAI TTS synthesized %d chars", len(text))
        return response.content

    except ImportError:
        logger.debug("openai package not installed — skipping OpenAI TTS")
        return None
    except Exception as exc:
        logger.warning("OpenAI TTS failed: %s", exc)
        return None


# ── Backend 2b: OpenAI TTS (mode-aware, with Kokoro fallback) ─────────────────

def _openai_tts(text: str) -> Optional[bytes]:
    """
    Synthesize via OpenAI TTS, reading key from config.
    Falls back to Kokoro daemon when key is not set.
    Returns None only on outright failure (caller handles further fallback).
    """
    try:
        from openai import OpenAI
        from app.config import get_config
        cfg = get_config()
        if not cfg.openai_api_key:
            logger.warning("OpenAI TTS requested but OPENAI_API_KEY not set — falling back to Kokoro")
            return _kokoro(text, _DEFAULT_VOICE)
        client = OpenAI(api_key=cfg.openai_api_key)
        response = client.audio.speech.create(
            model="tts-1",
            voice="onyx",
            input=text,
            response_format="wav",
        )
        logger.debug("OpenAI TTS synthesized %d chars", len(text))
        return response.content
    except Exception as e:
        logger.error("OpenAI TTS error: %s", e)
        return None


# ── Backend 3: macOS say ──────────────────────────────────────────────────────

def _say(text: str) -> None:
    """Play audio locally via macOS say. No bytes returned."""
    import subprocess
    try:
        subprocess.run(["say", "-v", "Daniel", text], check=False, timeout=30)
        logger.debug("macOS say played %d chars", len(text))
    except FileNotFoundError:
        logger.warning("macOS say not available (not on macOS?)")
    except Exception as exc:
        logger.warning("macOS say failed: %s", exc)


# ── Public interface ──────────────────────────────────────────────────────────

def speak(text: str, voice: str = _DEFAULT_VOICE) -> Optional[bytes]:
    """
    Synthesize text to WAV bytes, respecting cfg.tts_mode.

    browser  → return None immediately (frontend uses Web Speech API)
    openai   → call OpenAI TTS; return None on failure (frontend falls back)
    kokoro   → call Kokoro; fall back to OpenAI then macOS say

    Returns WAV bytes, or None if browser mode / all backends failed.
    """
    global _active_backend
    from app.config import get_config

    clean_text = _clean(text)
    if not clean_text:
        return None

    cfg = get_config()

    if cfg.tts_mode == "browser":
        return None  # frontend uses Web Speech API — no server synthesis needed

    if cfg.tts_mode == "openai":
        wav = _openai_tts(clean_text)
        if wav:
            _active_backend = "openai"
            return wav
        logger.warning("OpenAI TTS failed — falling back to Kokoro")
        wav = _kokoro(clean_text, voice)
        if wav:
            _active_backend = "kokoro"
        return wav

    # kokoro mode: full fallback chain
    wav = _kokoro(clean_text, voice)
    if wav:
        _active_backend = "kokoro"
        return wav

    wav = _openai(clean_text)
    if wav:
        _active_backend = "openai"
        return wav

    _say(clean_text)
    _active_backend = "say"
    return None


def active_backend() -> str:
    """Return the name of the last-used TTS backend."""
    return _active_backend


def backend_status() -> dict:
    """
    Summary of all backend availability — for the status endpoint.
    """
    # Check Kokoro
    kokoro_state = "unknown"
    kokoro_stats = {}
    try:
        from app.voice.kokoro_daemon import get_daemon
        d = get_daemon()
        kokoro_state = d.state
        kokoro_stats = d.status
    except Exception:
        kokoro_state = "import_error"

    # Check OpenAI
    openai_available = bool(os.environ.get("OPENAI_API_KEY"))
    try:
        import openai  # noqa: F401
        openai_installed = True
    except ImportError:
        openai_installed = False

    # Check say
    import shutil
    say_available = shutil.which("say") is not None

    return {
        "active_backend": _active_backend,
        "kokoro": {
            "state": kokoro_state,
            **kokoro_stats,
        },
        "openai_tts": {
            "available": openai_available and openai_installed,
            "key_set": openai_available,
            "package_installed": openai_installed,
        },
        "macos_say": {
            "available": say_available,
        },
    }
