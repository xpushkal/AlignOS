"""Security primitives: rate limiting, input sanitization, and output escaping.

Centralizes the defenses used across the Slack layer, the LLM layer, and the
FastAPI endpoints:

- `RateLimiter` — sliding-window limiter to bound abuse / cost / DoS (V1).
- `sanitize_text` / `wrap_untrusted` — neutralize and isolate untrusted user
  content before it reaches the LLM, mitigating prompt injection (V2, V6).
- `escape_slack` — escape untrusted text rendered into Slack mrkdwn so stored
  content cannot trigger notifications like <!channel> (V5).
"""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from app.config import get_settings

# Control chars except tab/newline/carriage-return.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Markers used to fence untrusted content in prompts. Chosen to be unlikely in
# normal text; any occurrence in user input is stripped by sanitize_text so the
# fence cannot be spoofed.
_FENCE_OPEN = "<<<UNTRUSTED_INPUT>>>"
_FENCE_CLOSE = "<<<END_UNTRUSTED_INPUT>>>"


def sanitize_text(text: str | None, max_len: int | None = None) -> str:
    """Strip control chars, collapse whitespace, drop fence markers, truncate.

    Used on every piece of user-supplied content before it is logged, stored, or
    embedded in an LLM prompt.
    """
    if not text:
        return ""
    if max_len is None:
        max_len = get_settings().max_input_chars
    cleaned = _CONTROL_CHARS.sub(" ", text)
    # Prevent the user from spoofing the prompt fence.
    cleaned = cleaned.replace(_FENCE_OPEN, "").replace(_FENCE_CLOSE, "")
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned


def wrap_untrusted(text: str | None) -> str:
    """Fence untrusted content so the model can tell data from instructions."""
    return f"{_FENCE_OPEN}\n{sanitize_text(text)}\n{_FENCE_CLOSE}"


def escape_slack(text: str | None) -> str:
    """Escape the three characters Slack mrkdwn treats specially (& < >)."""
    if not text:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class RateLimiter:
    """In-process sliding-window rate limiter.

    `check(key)` returns True if the call is allowed and records it, or False if
    the key has exceeded `max_calls` within `window_seconds`. State is in-memory
    (per process); a multi-instance deployment should back this with Redis.
    """

    def __init__(self, max_calls: int, window_seconds: int) -> None:
        self.max_calls = max_calls
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window
        dq = self._hits[key]
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= self.max_calls:
            if not dq:  # keep the map from growing unbounded
                self._hits.pop(key, None)
            return False
        dq.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()
