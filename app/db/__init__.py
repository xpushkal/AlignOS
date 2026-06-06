"""Database layer for AlignOS.

Exposes a `Repository` protocol with two implementations:

- `SupabaseRepository` — backed by Supabase Postgres (used when configured).
- `InMemoryRepository` — a dependency-free fallback used for local dev, tests,
  and the demo harness when Supabase credentials are absent.

`get_repository()` returns the appropriate one based on settings.
"""
from __future__ import annotations

from app.config import get_settings

from .base import Repository
from .memory import InMemoryRepository

_repo: Repository | None = None


def get_repository() -> Repository:
    """Return a process-wide singleton repository."""
    global _repo
    if _repo is not None:
        return _repo

    settings = get_settings()
    if settings.supabase_configured:
        from .supabase_repo import SupabaseRepository

        _repo = SupabaseRepository(settings.supabase_url, settings.supabase_service_key)
    else:
        _repo = InMemoryRepository()
    return _repo


def reset_repository() -> None:
    """Test helper — drop the cached singleton."""
    global _repo
    _repo = None


__all__ = ["Repository", "InMemoryRepository", "get_repository", "reset_repository"]
