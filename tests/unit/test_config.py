"""
Unit tests for app.config — the single source of runtime truth.

Config is the one place where a bad value should crash the app *on startup*
with a clear message rather than silently in production, so the custom
validators are the thing worth pinning: a malformed Anthropic key or an
invalid IANA timezone must raise, and the API-key minimum length must hold.
"""

import pytest
from pydantic import ValidationError

from app.config import JarvisConfig, get_config


class TestValidators:
    def test_anthropic_key_must_have_sk_ant_prefix(self):
        with pytest.raises(ValidationError) as exc:
            JarvisConfig(anthropic_api_key="not-a-real-prefix")
        assert "sk-ant-" in str(exc.value)

    def test_valid_anthropic_key_is_accepted(self):
        cfg = JarvisConfig(anthropic_api_key="sk-ant-something")
        assert cfg.anthropic_api_key == "sk-ant-something"

    def test_invalid_timezone_raises(self):
        with pytest.raises(ValidationError) as exc:
            JarvisConfig(timezone="Mars/Olympus_Mons")
        assert "Invalid timezone" in str(exc.value)

    @pytest.mark.parametrize("tz", ["America/Chicago", "America/New_York", "UTC"])
    def test_valid_timezones_accepted(self, tz):
        assert JarvisConfig(timezone=tz).timezone == tz

    def test_jarvis_api_key_below_min_length_rejected(self):
        with pytest.raises(ValidationError):
            JarvisConfig(jarvis_api_key="too-short")

    def test_jarvis_api_port_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            JarvisConfig(jarvis_api_port=80)  # below the ge=1024 floor


class TestComputedProperties:
    def test_is_production_true_only_in_production(self):
        assert JarvisConfig(environment="production").is_production is True
        assert JarvisConfig(environment="development").is_production is False

    def test_project_root_points_at_repo_root(self):
        cfg = JarvisConfig()
        # app/config/__init__.py -> three parents up is the repo root holding app/
        assert (cfg.project_root / "app").is_dir()

    def test_log_path_is_under_project_root(self):
        cfg = JarvisConfig(log_dir="logs")
        assert cfg.log_path == cfg.project_root / "logs"


class TestDefaults:
    def test_owner_title_defaults_to_boss(self, monkeypatch):
        monkeypatch.delenv("OWNER_TITLE", raising=False)
        assert JarvisConfig().owner_title == "Boss"

    def test_model_defaults(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_MODEL_DEFAULT", raising=False)
        monkeypatch.delenv("CLAUDE_MODEL_COMPLEX", raising=False)
        cfg = JarvisConfig()
        assert "haiku" in cfg.claude_model_default
        assert "sonnet" in cfg.claude_model_complex


class TestCaching:
    def test_get_config_is_cached(self):
        get_config.cache_clear()
        assert get_config() is get_config()
