"""
Shared pytest configuration and fixtures for the JARVIS Cloud suite.

Two jobs happen here, both BEFORE any application module is imported:

1. A deterministic test environment is injected into os.environ so that
   `app.config` validates and loads without a real `.env` file or real
   secrets. The keys are obviously fake but structurally valid (the
   Anthropic key starts with ``sk-ant-``; JARVIS_API_KEY clears the
   16-char minimum).

2. The heavy, slow-to-install voice dependencies (torch, kokoro,
   transformers, soundfile, sounddevice, and the SQLCipher driver) are
   registered as lightweight stub modules in ``sys.modules``. Nothing the
   suite exercises imports them, but the stubs mean CI can install a slim
   requirements set and a stray import can never drag a ~2GB torch wheel
   into the run. This is the "mock at the boundary" decision: we isolate
   the fast, deterministic business logic from the ML/audio runtime.

conftest is imported by pytest before any test module, so setting the
environment here guarantees it is in place before ``app.usage.tracker``
runs its import-time ``mkdir`` on USAGE_FILE.
"""

import os
import sys
import tempfile
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Deterministic environment — must be set before `app.*` is imported.
# ---------------------------------------------------------------------------
_USAGE_DIR = Path(tempfile.mkdtemp(prefix="jarvis-usage-"))

_TEST_ENV = {
    "OWNER_NAME": "TestBoss",
    "OWNER_TITLE": "Boss",
    "TIMEZONE": "America/Chicago",
    "LOCATION_CITY": "Bullard, TX",
    "LOCATION_LAT": "32.1374",
    "LOCATION_LON": "-95.3294",
    "ENVIRONMENT": "development",
    "DEBUG": "true",
    # Structurally valid but fake. 16+ chars for JARVIS_API_KEY's min_length.
    "JARVIS_API_KEY": "test-jarvis-key-0123456789",
    "JARVIS_API_HOST": "0.0.0.0",
    "JARVIS_API_PORT": "5001",
    "ANTHROPIC_API_KEY": "sk-ant-test-not-a-real-key",
    "CLAUDE_MODEL_DEFAULT": "claude-haiku-4-5-20251001",
    "CLAUDE_MODEL_COMPLEX": "claude-sonnet-4-5",
    "OPENWEATHER_API_KEY": "",
    "OPENAI_API_KEY": "",
    "LOG_LEVEL": "INFO",
    # Redirect the usage tracker's JSON store into a throwaway temp dir so its
    # import-time mkdir never touches /app/data on a CI runner.
    "USAGE_FILE": str(_USAGE_DIR / "usage.json"),
}

for _k, _v in _TEST_ENV.items():
    os.environ[_k] = _v


# ---------------------------------------------------------------------------
# 2. Stub the heavy voice/ML/crypto deps so CI never has to install them.
# ---------------------------------------------------------------------------
def _stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__["__is_test_stub__"] = True
    return mod


for _heavy in (
    "torch",
    "kokoro",
    "transformers",
    "soundfile",
    "sounddevice",
    "sqlcipher3",
    "pysqlcipher3",
):
    sys.modules.setdefault(_heavy, _stub(_heavy))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
import pytest  # noqa: E402  (import after env setup, intentionally)


@pytest.fixture
def fresh_config():
    """
    Return a freshly-built JarvisConfig with the test environment, bypassing
    the module-level lru_cache so a test can mutate env and see the effect.
    """
    from app.config import JarvisConfig, get_config

    get_config.cache_clear()
    cfg = JarvisConfig()
    yield cfg
    get_config.cache_clear()
