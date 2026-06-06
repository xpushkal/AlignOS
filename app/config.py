"""Application settings loaded from environment / .env.

See .env.example for the full list. Settings are intentionally lenient: the app
must import and expose /health even when external credentials are absent, so
optional integrations are gated on `is_configured` helpers rather than hard
failures at import time.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "development"
    port: int = 8000
    log_level: str = "INFO"

    # Slack
    slack_bot_token: str | None = None
    slack_signing_secret: str | None = None
    slack_app_token: str | None = None

    # Supabase
    supabase_url: str | None = None
    supabase_service_key: str | None = None

    # LLM
    anthropic_api_key: str | None = None
    llm_model: str = "claude-opus-4-8"

    # Real-Time Search
    slack_rts_enabled: bool = False

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_bot_token and self.slack_signing_secret)

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def llm_configured(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
