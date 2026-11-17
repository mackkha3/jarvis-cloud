"""
Unit tests for the Deepgram STT client (app/voice/stt.py).

No network: a fake httpx client is injected via ``transcribe(client=...)``. These
pin the parse path, the retry/timeout policy, and — critically — that the
transcript text and API key never reach the logs.
"""

import httpx
import pytest

from app.voice import stt
from app.voice.stt import STTError, transcribe

GOOD_BODY = {
    "metadata": {"duration": 3.5},
    "results": {"channels": [{"alternatives": [
        {"transcript": "add a task to call Jeremy at 4:30 tomorrow", "confidence": 0.987}
    ]}]},
}


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


class FakeClient:
    """Records calls and returns queued responses (or raises queued errors)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, params=None, headers=None, content=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "content": content})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestSuccess:
    def test_parses_text_confidence_duration(self):
        c = FakeClient([FakeResponse(200, GOOD_BODY)])
        out = transcribe(b"audiobytes", "audio/webm", api_key="sk-x", client=c)
        assert out["text"].startswith("add a task")
        assert out["confidence"] == 0.987
        assert out["audio_seconds"] == 3.5     # from metadata.duration
        assert out["provider"] == "deepgram"
        assert out["latency_ms"] >= 0.0

    def test_sends_model_and_auth(self):
        c = FakeClient([FakeResponse(200, GOOD_BODY)])
        transcribe(b"x", "audio/mp4", api_key="sk-secret", client=c)
        call = c.calls[0]
        assert call["params"]["model"] == "nova-3"
        assert call["params"]["smart_format"] == "true"
        assert call["headers"]["Authorization"] == "Token sk-secret"
        assert call["headers"]["Content-Type"] == "audio/mp4"


class TestFailureModes:
    def test_missing_key_raises_401(self):
        with pytest.raises(STTError) as ei:
            transcribe(b"x", "audio/webm", api_key="")
        assert ei.value.status == 401

    def test_empty_audio_raises_400(self):
        with pytest.raises(STTError) as ei:
            transcribe(b"", "audio/webm", api_key="sk-x")
        assert ei.value.status == 400

    def test_4xx_does_not_retry(self):
        c = FakeClient([FakeResponse(401), FakeResponse(200, GOOD_BODY)])
        with pytest.raises(STTError) as ei:
            transcribe(b"x", "audio/webm", api_key="sk-x", client=c)
        assert ei.value.status == 401
        assert len(c.calls) == 1  # no retry on a client error

    def test_5xx_retries_once_then_raises(self):
        c = FakeClient([FakeResponse(503), FakeResponse(503)])
        with pytest.raises(STTError) as ei:
            transcribe(b"x", "audio/webm", api_key="sk-x", client=c)
        assert ei.value.status == 503
        assert len(c.calls) == 2  # one retry

    def test_5xx_then_success(self):
        c = FakeClient([FakeResponse(500), FakeResponse(200, GOOD_BODY)])
        out = transcribe(b"x", "audio/webm", api_key="sk-x", client=c)
        assert out["text"].startswith("add a task")
        assert len(c.calls) == 2

    def test_timeout_raises_504_without_retry(self):
        c = FakeClient([httpx.TimeoutException("slow"), FakeResponse(200, GOOD_BODY)])
        with pytest.raises(STTError) as ei:
            transcribe(b"x", "audio/webm", api_key="sk-x", client=c)
        assert ei.value.status == 504
        assert len(c.calls) == 1  # timeout is not retried

    def test_malformed_body_raises(self):
        c = FakeClient([FakeResponse(200, {"results": {}})])
        with pytest.raises(STTError):
            transcribe(b"x", "audio/webm", api_key="sk-x", client=c)


class TestNoSecretLeak:
    def test_logs_contain_no_transcript_or_key(self, caplog):
        caplog.set_level("INFO", logger="jarvis.voice.stt")
        c = FakeClient([FakeResponse(200, GOOD_BODY)])
        transcribe(b"x", "audio/webm", api_key="sk-super-secret-key", client=c)
        assert "sk-super-secret-key" not in caplog.text
        assert "Jeremy" not in caplog.text
        assert "call Jeremy" not in caplog.text
        # but the safe telemetry is present
        assert "provider=deepgram" in caplog.text

    def test_upstream_error_logs_no_key(self, caplog):
        caplog.set_level("WARNING", logger="jarvis.voice.stt")
        c = FakeClient([FakeResponse(503), FakeResponse(503)])
        with pytest.raises(STTError):
            transcribe(b"x", "audio/webm", api_key="sk-super-secret-key", client=c)
        assert "sk-super-secret-key" not in caplog.text
