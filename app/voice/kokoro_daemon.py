"""
JARVIS Cloud — Kokoro TTS Daemon

Persistent daemon that loads the Kokoro-82M model once and serves synthesis
requests, eliminating the 10-15s cold-start cost of spawning a fresh subprocess.

Architecture:
- Singleton KokoroDaemon, started once in a daemon thread at Flask startup
- Model loaded asynchronously — Flask continues while Kokoro warms up in background
- Synthesis serialized via threading.Lock (one at a time, single model)
- Socket server at /tmp/jarvis_kokoro_<PID>.sock for external callers
- Per-PID path is safe under gunicorn multi-worker (each worker owns its socket)

Segfault note (vs old subprocess approach):
- Old code: subprocess per call → segfault kills child, not Flask (but 10-15s per call)
- This approach: thread per call → hard segfault would kill Flask process
- On Linux/Railway, PyTorch (CPU-mode) is stable; the MPS-specific crashes that
  motivated the subprocess approach don't occur. Railway auto-restarts on crash.
- KMP_DUPLICATE_LIB_OK and PYTORCH_ENABLE_MPS_FALLBACK are still set defensively.
"""

# These must be the very first lines after the docstring — before any import
# that could transitively pull in torch or libiomp. Matches old kokoro_tts.py exactly.
import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'

import base64
import io
import json
import logging
import socket
import struct
import threading
import time
from collections import deque
from datetime import datetime
from typing import Optional

logger = logging.getLogger("jarvis.voice.kokoro")

# Per-process socket path — safe for gunicorn multi-worker
SOCKET_PATH = f"/tmp/jarvis_kokoro_{os.getpid()}.sock"

_DEFAULT_VOICE = "bm_george"
_SAMPLE_RATE = 24000
_WARMUP_TEXT = "JARVIS online."
_LATENCY_WINDOW = 20  # rolling window for latency stats


class DaemonState:
    INIT = "initializing"
    LOADING = "loading_model"
    READY = "ready"
    ERROR = "error"
    STOPPED = "stopped"


class KokoroDaemon:
    """
    Singleton persistent TTS daemon. Get the instance via get_daemon().
    Call start() once during app startup.
    """

    _instance: Optional["KokoroDaemon"] = None
    _lock_cls = threading.Lock()

    def __new__(cls) -> "KokoroDaemon":
        with cls._lock_cls:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init_state()
                cls._instance = instance
        return cls._instance

    def _init_state(self) -> None:
        self.state: str = DaemonState.INIT
        self.error_message: str = ""
        self._pipe = None
        self._synth_lock = threading.Lock()
        self._latencies: deque = deque(maxlen=_LATENCY_WINDOW)
        self._request_count: int = 0
        self._error_count: int = 0
        self._started_at: Optional[datetime] = None
        self._ready_at: Optional[datetime] = None
        self._thread: Optional[threading.Thread] = None

    # ── Startup ──────────────────────────────────────────────

    def start(self) -> None:
        """Start the daemon thread. Idempotent — safe to call multiple times."""
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="kokoro-daemon",
            daemon=True,
        )
        self._thread.start()
        logger.info("Kokoro daemon thread started (pid=%d socket=%s)", os.getpid(), SOCKET_PATH)

    def _run(self) -> None:
        self._started_at = datetime.now()
        self.state = DaemonState.LOADING

        if self._load_model():
            self._warmup()
            self.state = DaemonState.READY
            self._ready_at = datetime.now()
            elapsed = (self._ready_at - self._started_at).total_seconds()
            logger.info("Kokoro READY — model loaded in %.1fs", elapsed)
        else:
            self.state = DaemonState.ERROR
            logger.warning(
                "Kokoro model unavailable (%s) — daemon running in error state",
                self.error_message,
            )

        self._serve()

    # ── Model loading ─────────────────────────────────────────

    def _load_model(self) -> bool:
        try:
            import warnings
            logger.info("Loading Kokoro-82M (first run downloads ~82MB from HuggingFace)...")
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=UserWarning)
                from kokoro import KPipeline
                self._pipe = KPipeline(lang_code='b', repo_id='hexgrad/Kokoro-82M')
            logger.info("Kokoro model loaded")
            return True

        except ImportError as exc:
            self.error_message = f"kokoro not installed: {exc}"
            logger.warning(
                "Kokoro package not installed. Install: pip install kokoro soundfile numpy. "
                "Falling back to OpenAI TTS or macOS say."
            )
            return False

        except Exception as exc:
            self.error_message = f"model load failed: {exc}"
            logger.error("Kokoro model load failed: %s", exc, exc_info=True)
            return False

    def _warmup(self) -> None:
        """Synthesize a short phrase to trigger any JIT compilation paths."""
        try:
            t0 = time.monotonic()
            self._synthesize_raw(_WARMUP_TEXT, _DEFAULT_VOICE)
            logger.info("Kokoro warmup complete in %.0fms", (time.monotonic() - t0) * 1000)
        except Exception as exc:
            logger.warning("Warmup failed (non-fatal): %s", exc)

    # ── Synthesis ─────────────────────────────────────────────

    def _synthesize_raw(self, text: str, voice: str) -> bytes:
        """
        Run Kokoro synthesis. Returns raw WAV bytes.
        Must be called with self._synth_lock held.
        Raises on any failure.
        """
        import numpy as np
        import soundfile as sf

        chunks = []
        for result in self._pipe(text, voice=voice):
            # Kokoro yields (graphemes, phonemes, audio_tensor)
            chunks.append(result[2].numpy())

        audio = np.concatenate(chunks) if chunks else np.array([], dtype=np.float32)

        buf = io.BytesIO()
        sf.write(buf, audio, _SAMPLE_RATE, format="WAV")
        return buf.getvalue()

    def synthesize(self, text: str, voice: str = _DEFAULT_VOICE) -> dict:
        """
        Public synthesis entry point. Thread-safe.
        Returns {"audio": "<base64 WAV>", "duration_ms": N} or {"error": "..."}.
        """
        if self.state != DaemonState.READY:
            return {"error": f"daemon_{self.state}"}

        t0 = time.monotonic()
        try:
            with self._synth_lock:
                wav_bytes = self._synthesize_raw(text, voice)

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self._latencies.append(elapsed_ms)
            self._request_count += 1

            return {
                "audio": base64.b64encode(wav_bytes).decode("ascii"),
                "duration_ms": elapsed_ms,
                "voice": voice,
            }

        except Exception as exc:
            self._error_count += 1
            logger.error("Synthesis failed for %r: %s", text[:60], exc)
            return {"error": str(exc)}

    # ── Socket server ─────────────────────────────────────────

    def _serve(self) -> None:
        """
        Unix socket server. Accepts connections in a loop; each connection
        is handled in its own thread so concurrent HTTP requests don't queue
        at the accept() call.
        """
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass

        try:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(SOCKET_PATH)
            os.chmod(SOCKET_PATH, 0o600)
            srv.listen(8)
            logger.info("Kokoro socket ready at %s", SOCKET_PATH)
        except Exception as exc:
            logger.error("Cannot bind socket %s: %s", SOCKET_PATH, exc)
            return

        while True:
            try:
                conn, _ = srv.accept()
                threading.Thread(
                    target=self._handle_conn,
                    args=(conn,),
                    daemon=True,
                ).start()
            except Exception as exc:
                logger.debug("Socket accept error: %s", exc)
                time.sleep(0.05)

    def _handle_conn(self, conn: socket.socket) -> None:
        """Handle one client connection: read request, synthesize, return response."""
        try:
            with conn:
                # Read 4-byte big-endian length prefix + JSON body
                header = _recv_exact(conn, 4)
                if not header:
                    return
                length = struct.unpack(">I", header)[0]
                if length > 1_000_000:  # sanity limit: 1MB request
                    return
                body = _recv_exact(conn, length)
                if not body:
                    return

                req = json.loads(body.decode("utf-8"))
                text = (req.get("text") or "").strip()
                voice = req.get("voice") or _DEFAULT_VOICE

                if not text:
                    response = {"error": "empty_text"}
                else:
                    response = self.synthesize(text, voice)

                payload = json.dumps(response).encode("utf-8")
                conn.sendall(struct.pack(">I", len(payload)) + payload)

        except Exception as exc:
            logger.debug("Connection handler error: %s", exc)

    # ── Status ────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self.state == DaemonState.READY

    @property
    def status(self) -> dict:
        lats = list(self._latencies)
        avg_ms = int(sum(lats) / len(lats)) if lats else None
        p95_ms = sorted(lats)[int(len(lats) * 0.95)] if len(lats) >= 5 else None
        load_s = None
        if self._started_at and self._ready_at:
            load_s = round((self._ready_at - self._started_at).total_seconds(), 1)

        return {
            "state": self.state,
            "socket_path": SOCKET_PATH,
            "requests_total": self._request_count,
            "errors_total": self._error_count,
            "latency_avg_ms": avg_ms,
            "latency_p95_ms": p95_ms,
            "model_load_time_s": load_s,
            "error_message": self.error_message or None,
        }


# ── Helpers ───────────────────────────────────────────────────

def _recv_exact(conn: socket.socket, n: int) -> Optional[bytes]:
    """Read exactly n bytes from socket. Returns None on early close."""
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def get_daemon() -> KokoroDaemon:
    """Return the singleton KokoroDaemon instance."""
    return KokoroDaemon()
