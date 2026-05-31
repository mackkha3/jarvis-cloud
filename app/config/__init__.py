"""
JARVIS Cloud — Configuration System

Single source of truth for all runtime configuration.
Loads from environment variables (.env file or system env),
validates everything via Pydantic, and exposes a typed config
object to the rest of the application.

If required values are missing or malformed, JARVIS fails fast
on startup with a clear error message — never silently in production.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root — the directory containing this app/ folder
# __file__ is app/config/__init__.py so we need three .parent calls
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class JarvisConfig(BaseSettings):
    """
    Master configuration for JARVIS Cloud.

    All values load from environment variables. In development,
    these come from a .env file in the project root. In production
    (Railway), they come from the Railway dashboard's environment
    variable settings.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== CUSTOMER IDENTITY =====
    # These personalize JARVIS for the specific person it serves.
    owner_name: str = Field(
        ...,
        description="The customer's preferred name (e.g., 'Mike', 'Sarah'). "
                    "JARVIS uses this when addressing them.",
    )
    owner_title: str = Field(
        default="Boss",
        description="How JARVIS addresses the owner (e.g., 'Boss', 'Sir', 'Ma'am').",
    )
    timezone: str = Field(
        default="America/Chicago",
        description="IANA timezone string (e.g., 'America/Chicago', 'America/New_York').",
    )
    location_city: str = Field(
        default="",
        description="City for weather and location-aware features.",
    )
    location_lat: float = Field(
        default=0.0,
        description="Latitude for weather lookups.",
    )
    location_lon: float = Field(
        default=0.0,
        description="Longitude for weather lookups.",
    )

    # ===== ENVIRONMENT =====
    environment: Literal["development", "production"] = Field(
        default="development",
        description="Runtime environment. Affects logging, debug mode, etc.",
    )
    debug: bool = Field(
        default=True,
        description="Enable debug mode. Should be False in production.",
    )

    # ===== JARVIS API =====
    jarvis_api_key: str = Field(
        ...,
        min_length=16,
        description="The API key required to authenticate requests to JARVIS. "
                    "Generate a random 32+ character string. NEVER share.",
    )
    jarvis_api_host: str = Field(
        default="0.0.0.0",
        description="Network interface to bind to. 0.0.0.0 = all interfaces.",
    )
    jarvis_api_port: int = Field(
        default=5001,
        ge=1024,
        le=65535,
        description="Port for the Flask API (5001 in dev to avoid conflict with old jarvis).",
    )

    # ===== ANTHROPIC =====
    anthropic_api_key: str = Field(
        ...,
        description="Anthropic API key (starts with 'sk-ant-'). "
                    "Get from console.anthropic.com.",
    )
    claude_model_default: str = Field(
        default="claude-haiku-4-5-20251001",
        description="Default Claude model for routine queries (Layer 2).",
    )
    claude_model_complex: str = Field(
        default="claude-sonnet-4-5",
        description="Claude model for complex reasoning (Layer 3).",
    )

    # ===== GOOGLE INTEGRATIONS =====
    google_credentials_path: str = Field(
        default="credentials.json",
        description="Path to Google OAuth credentials.json file.",
    )
    google_token_path: str = Field(
        default="google_token.json",
        description="Path where the OAuth token will be saved after first auth.",
    )

    # ===== WEATHER =====
    openweather_api_key: str = Field(
        default="",
        description="OpenWeatherMap API key (free tier OK). "
                    "Leave blank to disable weather features.",
    )

    # ===== VOICE / TTS =====
    tts_mode: Literal["browser", "openai", "kokoro"] = Field(
        default="browser",
        description="TTS mode: browser (device voice, free), openai (fast, API cost), kokoro (local, slow)",
    )
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for TTS. Required only if tts_mode=openai.",
    )

    # ===== LOGGING =====
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging verbosity.",
    )
    log_dir: str = Field(
        default="logs",
        description="Directory for log files (relative to project root).",
    )

    # ===== VALIDATORS =====
    @field_validator("anthropic_api_key")
    @classmethod
    def validate_anthropic_key(cls, v: str) -> str:
        """Anthropic keys start with 'sk-ant-'. Catch obvious typos early."""
        if not v.startswith("sk-ant-"):
            raise ValueError(
                "ANTHROPIC_API_KEY must start with 'sk-ant-'. "
                "Get one at https://console.anthropic.com/"
            )
        return v

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Ensure the timezone string is valid IANA format."""
        import zoneinfo
        try:
            zoneinfo.ZoneInfo(v)
        except zoneinfo.ZoneInfoNotFoundError:
            raise ValueError(
                f"Invalid timezone: '{v}'. "
                f"Use IANA format like 'America/Chicago'. "
                f"Full list: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones"
            )
        return v

    # ===== COMPUTED PROPERTIES =====
    @property
    def project_root(self) -> Path:
        """Absolute path to the project root directory."""
        return PROJECT_ROOT

    @property
    def log_path(self) -> Path:
        """Absolute path to the log directory."""
        return PROJECT_ROOT / self.log_dir

    @property
    def is_production(self) -> bool:
        """Quick check for production environment."""
        return self.environment == "production"


@lru_cache
def get_config() -> JarvisConfig:
    """
    Returns the validated JARVIS configuration.

    Cached so repeated calls don't re-parse the .env file.
    Call this from anywhere in the app to access config values:

        from app.config import get_config
        cfg = get_config()
        print(cfg.owner_name)
    """
    return JarvisConfig()


# Convenience export — most modules will import this directly
config = get_config
