"""Database layer for AlignOS.

Exposes a `Repository` protocol with two implementations:

- `PostgresRepository` — backed by Neon PostgreSQL via psycopg (used when
  `DATABASE_URL` is configured).
- `InMemoryRepository` — a dependency-free fallback used for local dev, tests,
  and the demo harness when no database is configured.

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
    if settings.database_configured:
        from .postgres_repo import PostgresRepository

        _repo = PostgresRepository(settings.database_url)
    else:
        _repo = InMemoryRepository()
    return _repo


def reset_repository() -> None:
    """Test helper — drop the cached singleton."""
    global _repo
    _repo = None


__all__ = ["Repository", "InMemoryRepository", "get_repository", "reset_repository"]
