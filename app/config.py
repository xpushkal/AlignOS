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

    # Database (Neon PostgreSQL)
    database_url: str | None = None

    # LLM (OpenRouter — OpenAI-compatible API)
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Real-Time Search
    slack_rts_enabled: bool = False

    # Security / rate limiting
    max_input_chars: int = 4000
    rate_limit_max_calls: int = 20
    rate_limit_window_seconds: int = 60
    agent_api_token: str | None = None  # if set, /agent/* requires X-AlignOS-Token

    # Concurrency / scale
    max_concurrency: int = 8       # max blocking (DB/LLM) tasks running at once
    db_pool_max_size: int = 10     # Neon connection pool size (>= max_concurrency)

    @property
    def slack_configured(self) -> bool:
        return bool(self.slack_bot_token and self.slack_signing_secret)

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def llm_configured(self) -> bool:
        return bool(self.openrouter_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
