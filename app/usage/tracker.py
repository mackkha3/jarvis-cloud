"""Persistent token usage and cost tracker for Claude + OpenAI TTS."""
import json
import os
import threading
from datetime import datetime
from pathlib import Path
import pytz

import logging
logger = logging.getLogger("jarvis.usage")

# Pricing per 1M tokens (Claude) / per 1M chars (OpenAI TTS)
# Updated as of May 2026 — verify current rates
PRICING = {
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-opus-4-7": {"input": 15.00, "output": 75.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "openai-tts": 15.00,  # per 1M characters (tts-1)
}

USAGE_FILE = Path(os.environ.get("USAGE_FILE", "/app/data/usage.json"))
USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_CT = pytz.timezone("America/Chicago")


def _load():
    if not USAGE_FILE.exists():
        return {"days": {}}
    try:
        return json.loads(USAGE_FILE.read_text())
    except Exception as e:
        logger.error(f"Usage file read error: {e}")
        return {"days": {}}


def _save(data):
    try:
        USAGE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Usage file write error: {e}")


def _today_key():
    return datetime.now(_CT).strftime("%Y-%m-%d")


def _month_key():
    return datetime.now(_CT).strftime("%Y-%m")


def _empty_day():
    return {"claude": 0.0, "openai_tts": 0.0, "claude_tokens_in": 0, "claude_tokens_out": 0, "tts_chars": 0}


def _resolve_rates(model: str):
    """Return pricing dict for model, or None if unknown."""
    if model in PRICING:
        rates = PRICING[model]
        if isinstance(rates, dict):
            return rates
    # Prefix match — handles versioned model IDs like claude-haiku-4-5-20251001
    for key, val in PRICING.items():
        if isinstance(val, dict) and model.startswith(key):
            return val
    return None


def record_claude(model: str, input_tokens: int, output_tokens: int):
    """Called from claude.py after each API response."""
    rates = _resolve_rates(model)
    if not rates:
        logger.warning(f"No pricing for model: {model} — cost not tracked")
        return

    cost = (input_tokens * rates["input"] / 1_000_000) + (output_tokens * rates["output"] / 1_000_000)

    with _lock:
        data = _load()
        day = _today_key()
        if day not in data["days"]:
            data["days"][day] = _empty_day()
        data["days"][day]["claude"] += cost
        data["days"][day]["claude_tokens_in"] += input_tokens
        data["days"][day]["claude_tokens_out"] += output_tokens
        _save(data)


def record_openai_tts(characters: int):
    """Called from tts.py after each TTS generation."""
    cost = characters * PRICING["openai-tts"] / 1_000_000
    with _lock:
        data = _load()
        day = _today_key()
        if day not in data["days"]:
            data["days"][day] = _empty_day()
        data["days"][day]["openai_tts"] += cost
        data["days"][day]["tts_chars"] += characters
        _save(data)


def get_summary():
    """Returns today + month-to-date totals for dashboard."""
    with _lock:
        data = _load()

    today = _today_key()
    month_prefix = _month_key()

    today_data = data["days"].get(today, {})
    today_claude = today_data.get("claude", 0.0)
    today_tts = today_data.get("openai_tts", 0.0)
    today_total = today_claude + today_tts

    mtd_claude = 0.0
    mtd_tts = 0.0
    for day, vals in data["days"].items():
        if day.startswith(month_prefix):
            mtd_claude += vals.get("claude", 0.0)
            mtd_tts += vals.get("openai_tts", 0.0)
    mtd_total = mtd_claude + mtd_tts

    return {
        "today": {
            "total": round(today_total, 4),
            "claude": round(today_claude, 4),
            "openai_tts": round(today_tts, 4),
            "claude_tokens_in": today_data.get("claude_tokens_in", 0),
            "claude_tokens_out": today_data.get("claude_tokens_out", 0),
            "tts_chars": today_data.get("tts_chars", 0),
        },
        "month_to_date": {
            "total": round(mtd_total, 4),
            "claude": round(mtd_claude, 4),
            "openai_tts": round(mtd_tts, 4),
        },
        "as_of": datetime.now(_CT).strftime("%H:%M CT"),
    }
