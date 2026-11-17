"""
Server-side speech-to-text via Deepgram.

A single ``transcribe()`` call posts raw audio bytes to Deepgram's pre-recorded
REST endpoint and returns the text plus the numbers we care about (confidence,
latency, audio seconds, provider). Deliberately thin: no SDK (httpx is already a
dependency), one short timeout, one retry on 5xx only, and — importantly — it
never logs transcript text or audio, only the provider, latency, audio seconds,
and status code. The endpoint and params are verified against Deepgram's current
docs: POST https://api.deepgram.com/v1/listen?model=nova-3&smart_format=true with
an ``Authorization: Token <key>`` header and the raw audio as the body.
"""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger("jarvis.voice.stt")

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
DEFAULT_MODEL = "nova-3"
PROVIDER = "deepgram"
TIMEOUT_SECONDS = 10.0


class STTError(Exception):
    """Raised when transcription cannot be completed."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _extract(payload: dict) -> tuple[str, float, float]:
    """Pull transcript, confidence, and audio duration from a Deepgram response."""
    try:
        alt = payload["results"]["channels"][0]["alternatives"][0]
        duration = float(payload.get("metadata", {}).get("duration", 0.0))
        return alt.get("transcript", ""), float(alt.get("confidence", 0.0)), duration
    except (KeyError, IndexError, TypeError) as exc:
        raise STTError(f"Unexpected Deepgram response shape: {exc}") from exc


def transcribe(
    audio_bytes: bytes,
    mimetype: str,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    audio_seconds: float = 0.0,
    client: httpx.Client | None = None,
) -> dict:
    """
    Transcribe ``audio_bytes`` with Deepgram and return a result dict:
    ``{text, confidence, latency_ms, audio_seconds, provider}``.

    Retries once on a 5xx, never on a 4xx. Raises ``STTError`` on failure. Never
    logs the transcript or the audio — only provider, latency, seconds, status.
    """
    if not api_key:
        raise STTError("Deepgram API key is not configured", status=401)
    if not audio_bytes:
        raise STTError("Empty audio body", status=400)

    params = {"model": model, "smart_format": "true"}
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": mimetype or "application/octet-stream",
    }

    owns_client = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS)
    started = time.perf_counter()
    try:
        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                resp = client.post(DEEPGRAM_URL, params=params, headers=headers, content=audio_bytes)
            except httpx.TimeoutException as exc:
                # A timeout is not a 5xx; surface it as a gateway failure without retry.
                logger.warning("STT timeout provider=%s attempt=%d", PROVIDER, attempt)
                raise STTError("Deepgram request timed out", status=504) from exc

            if resp.status_code >= 500:
                last_exc = STTError(f"Deepgram {resp.status_code}", status=resp.status_code)
                logger.warning("STT upstream %d provider=%s attempt=%d", resp.status_code, PROVIDER, attempt)
                if attempt == 1:
                    continue
                raise last_exc
            if resp.status_code >= 400:
                # 4xx (bad key, bad request) — do not retry.
                logger.warning("STT client error %d provider=%s", resp.status_code, PROVIDER)
                raise STTError(f"Deepgram {resp.status_code}", status=resp.status_code)

            text, confidence, duration = _extract(resp.json())
            # Deepgram reports the true decoded duration; prefer it for cost.
            seconds = duration or audio_seconds
            latency_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "STT ok provider=%s latency_ms=%.0f audio_seconds=%.2f status=%d",
                PROVIDER, latency_ms, seconds, resp.status_code,
            )
            return {
                "text": text,
                "confidence": round(confidence, 4),
                "latency_ms": round(latency_ms, 1),
                "audio_seconds": round(seconds, 2),
                "provider": PROVIDER,
            }
        raise last_exc or STTError("Deepgram request failed")
    finally:
        if owns_client:
            client.close()
