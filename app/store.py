"""Shared state store: rate limiting, event dedup, cache, and cache versioning.

Two backends:
- `InMemoryStore` (default) — per-process state; fine for a single instance.
- `RedisStore` — shared across instances, so AlignOS can run as multiple stateless
  replicas behind a load balancer (HTTP events). Selected when `REDIS_URL` is set.

All methods are async so the same interface works for both backends.

Cache invalidation uses a per-scope version counter: read keys embed the current
version, and a write (e.g. a confirmed decision) bumps the version, instantly
orphaning stale cache entries without scanning keys.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Protocol, runtime_checkable

from app.config import get_settings

_SEEN_MAX = 5000


@runtime_checkable
class Store(Protocol):
    backend: str

    async def rate_allow(self, key: str) -> bool: ...
    async def seen(self, event_id: str | None, ttl: int = 3600) -> bool: ...
    async def cache_get(self, key: str) -> str | None: ...
    async def cache_set(self, key: str, value: str, ttl: int) -> None: ...
    async def get_version(self, scope: str) -> int: ...
    async def bump_version(self, scope: str) -> int: ...


class InMemoryStore(Store):
    backend = "in-memory"

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._seen_ids: deque[str] = deque(maxlen=_SEEN_MAX)
        self._seen_set: set[str] = set()
        self._cache: dict[str, tuple[str, float]] = {}
        self._versions: dict[str, int] = defaultdict(int)

    async def rate_allow(self, key: str) -> bool:
        s = get_settings()
        now = time.monotonic()
        cutoff = now - s.rate_limit_window_seconds
        dq = self._hits[key]
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= s.rate_limit_max_calls:
            return False
        dq.append(now)
        return True

    async def seen(self, event_id: str | None, ttl: int = 3600) -> bool:
        if not event_id:
            return False
        if event_id in self._seen_set:
            return True
        self._seen_ids.append(event_id)
        self._seen_set.add(event_id)
        if len(self._seen_set) > _SEEN_MAX:
            self._seen_set.intersection_update(self._seen_ids)
        return False

    async def cache_get(self, key: str) -> str | None:
        entry = self._cache.get(key)
        if not entry:
            return None
        value, expires = entry
        if expires and expires < time.time():
            self._cache.pop(key, None)
            return None
        return value

    async def cache_set(self, key: str, value: str, ttl: int) -> None:
        self._cache[key] = (value, time.time() + ttl if ttl else 0.0)

    async def get_version(self, scope: str) -> int:
        return self._versions[scope]

    async def bump_version(self, scope: str) -> int:
        self._versions[scope] += 1
        return self._versions[scope]


class RedisStore(Store):
    backend = "redis"

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # lazy import

        self.r = aioredis.from_url(url, decode_responses=True)

    async def rate_allow(self, key: str) -> bool:
        # Fixed-window counter: INCR a per-window bucket and expire it.
        s = get_settings()
        window = s.rate_limit_window_seconds
        bucket = int(time.time() // window)
        rkey = f"rl:{key}:{bucket}"
        n = await self.r.incr(rkey)
        if n == 1:
            await self.r.expire(rkey, window)
        return n <= s.rate_limit_max_calls

    async def seen(self, event_id: str | None, ttl: int = 3600) -> bool:
        if not event_id:
            return False
        # SET NX returns True if newly set, None if it already existed (duplicate).
        created = await self.r.set(f"evt:{event_id}", "1", nx=True, ex=ttl)
        return not created

    async def cache_get(self, key: str) -> str | None:
        return await self.r.get(f"cache:{key}")

    async def cache_set(self, key: str, value: str, ttl: int) -> None:
        await self.r.set(f"cache:{key}", value, ex=ttl)

    async def get_version(self, scope: str) -> int:
        v = await self.r.get(f"ver:{scope}")
        return int(v) if v else 0

    async def bump_version(self, scope: str) -> int:
        return int(await self.r.incr(f"ver:{scope}"))


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is not None:
        return _store
    settings = get_settings()
    if settings.redis_configured:
        try:
            _store = RedisStore(settings.redis_url)
        except Exception:  # pragma: no cover - depends on optional dep/runtime
            import logging

            logging.getLogger("alignos.store").warning(
                "Redis unavailable; falling back to in-memory store."
            )
            _store = InMemoryStore()
    else:
        _store = InMemoryStore()
    return _store


def reset_store() -> None:
    """Test helper — drop the cached store."""
    global _store
    _store = None
