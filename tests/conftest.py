"""Test isolation.

Force the in-memory DB backend and the heuristic LLM mode regardless of any
local `.env`, so the suite is deterministic and never touches a real Neon
database or makes network calls. Setting these in os.environ overrides values
loaded from `.env` (env vars take precedence in pydantic-settings).
"""
import os

import pytest

os.environ["DATABASE_URL"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["SLACK_BOT_TOKEN"] = ""
os.environ["SLACK_SIGNING_SECRET"] = ""

# Clear any cached settings/singletons built during import.
from app import concurrency  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import reset_repository  # noqa: E402
from app.llm import get_llm_client  # noqa: E402
from app.security import reset_limiters  # noqa: E402

get_settings.cache_clear()
get_llm_client.cache_clear()
reset_repository()
reset_limiters()
concurrency.reset()


@pytest.fixture(autouse=True)
def _reset_state():
    """Keep DB, rate-limit, and concurrency state isolated between tests."""
    reset_repository()
    reset_limiters()
    concurrency.reset()
    yield
