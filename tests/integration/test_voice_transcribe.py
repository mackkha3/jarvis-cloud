"""
Integration tests for POST /api/voice/transcribe.

A throwaway Flask app mounts the real voice-chat routes; the Deepgram call is
mocked at app.voice.stt.transcribe, and the feature flag is toggled per test.
Covers the flag gate, auth, input validation, the success shape, cost tracking,
and clean 401/502 fallbacks.
"""

import pytest
from flask import Flask

from app.api.voice_routes import register_voice_chat_routes
from app.config import get_config
from app.voice.stt import STTError

VALID_KEY = "test-jarvis-key-0123456789"  # matches conftest's JARVIS_API_KEY
AUTH = {"X-API-Key": VALID_KEY}
GOOD = {"text": "what's on my calendar Thursday", "confidence": 0.95,
        "latency_ms": 180.0, "audio_seconds": 2.1, "provider": "deepgram"}


@pytest.fixture
def client():
    get_config.cache_clear()
    app = Flask(__name__)
    register_voice_chat_routes(app)
    app.testing = True
    return app.test_client()


def _enable(monkeypatch, on=True):
    monkeypatch.setattr("app.config.features.is_enabled",
                        lambda name: on and name == "deepgram_stt")


class TestGate:
    def test_flag_off_returns_404(self, client, monkeypatch):
        _enable(monkeypatch, on=False)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"x", content_type="audio/webm")
        assert r.status_code == 404

    def test_missing_api_key_returns_401(self, client, monkeypatch):
        _enable(monkeypatch)
        r = client.post("/api/voice/transcribe", data=b"x", content_type="audio/webm")
        assert r.status_code == 401


class TestValidation:
    def test_bad_mimetype_returns_415(self, client, monkeypatch):
        _enable(monkeypatch)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"x", content_type="application/json")
        assert r.status_code == 415

    def test_oversize_body_returns_413(self, client, monkeypatch):
        _enable(monkeypatch)
        big = b"0" * (10 * 1024 * 1024 + 1)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=big, content_type="audio/webm")
        assert r.status_code == 413

    def test_empty_body_returns_400(self, client, monkeypatch):
        _enable(monkeypatch)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"", content_type="audio/webm")
        assert r.status_code == 400


class TestSuccess:
    def test_success_returns_text_and_records_usage(self, client, monkeypatch):
        _enable(monkeypatch)
        monkeypatch.setattr("app.voice.stt.transcribe", lambda *a, **k: GOOD)
        recorded = {}
        monkeypatch.setattr("app.usage.tracker.record_deepgram_stt",
                            lambda seconds: recorded.setdefault("seconds", seconds))
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"audiobytes", content_type="audio/webm")
        assert r.status_code == 200
        body = r.get_json()
        assert body["text"] == GOOD["text"]
        assert body["confidence"] == 0.95
        assert body["latency_ms"] == 180.0
        assert recorded["seconds"] == 2.1  # audio minutes tracked

    def test_mp4_mimetype_is_accepted(self, client, monkeypatch):
        _enable(monkeypatch)
        monkeypatch.setattr("app.voice.stt.transcribe", lambda *a, **k: GOOD)
        monkeypatch.setattr("app.usage.tracker.record_deepgram_stt", lambda s: None)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"x", content_type="audio/mp4")  # iPhone Safari
        assert r.status_code == 200


class TestUpstreamFailure:
    def test_upstream_401_returns_401(self, client, monkeypatch):
        _enable(monkeypatch)
        def boom(*a, **k):
            raise STTError("bad key", status=401)
        monkeypatch.setattr("app.voice.stt.transcribe", boom)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"x", content_type="audio/webm")
        assert r.status_code == 401

    def test_upstream_5xx_returns_502(self, client, monkeypatch):
        _enable(monkeypatch)
        def boom(*a, **k):
            raise STTError("deepgram 503", status=503)
        monkeypatch.setattr("app.voice.stt.transcribe", boom)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"x", content_type="audio/webm")
        assert r.status_code == 502
        assert r.get_json()["error"] == "Transcription failed"

    def test_timeout_returns_502(self, client, monkeypatch):
        _enable(monkeypatch)
        def boom(*a, **k):
            raise STTError("timed out", status=504)
        monkeypatch.setattr("app.voice.stt.transcribe", boom)
        r = client.post("/api/voice/transcribe", headers=AUTH,
                        data=b"x", content_type="audio/webm")
        assert r.status_code == 502
