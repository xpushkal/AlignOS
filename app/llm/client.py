"""LLM client returning structured JSON for the AlignOS reasoning tasks.

Uses OpenRouter (OpenAI-compatible API) when configured. When no API key is
present it falls back to `app.llm.heuristics`, a deterministic rule-based engine
so the whole pipeline — detection, verification, conflict, summary — works
offline for local dev, tests, and the demo harness.

All public methods return plain dicts matching the JSON contracts in
Docs/MCP_TOOLS.md §3.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from app.config import get_settings

from . import heuristics

logger = logging.getLogger("alignos.llm")


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.openrouter_model
        self._client = None
        if settings.llm_configured:
            try:
                from openai import OpenAI  # lazy import

                self._client = OpenAI(
                    base_url=settings.openrouter_base_url,
                    api_key=settings.openrouter_api_key,
                )
            except Exception as exc:  # pragma: no cover - depends on optional dep
                logger.warning("OpenRouter client unavailable (%s); using heuristics.", exc)

    @property
    def mode(self) -> str:
        return "openrouter" if self._client else "heuristic"

    # --- public reasoning tasks ---
    def detect_decision(
        self, message: str, thread_context: str = "", recent_channel_context: str = ""
    ) -> dict[str, Any]:
        prompt = (
            "Classify whether the following Slack message finalizes a team decision. "
            "Return JSON with keys: is_decision (bool), title, summary, reason, "
            "participants (list), confidence (0-1), needs_confirmation (bool).\n\n"
            f"Thread context:\n{thread_context}\n\nRecent channel:\n"
            f"{recent_channel_context}\n\nMessage:\n{message}"
        )
        return self._json_or_heuristic(
            prompt, lambda: heuristics.detect_decision(message)
        )

    def verify_evidence(
        self, proposed_answer: str, evidence_messages: list[str], memory_items: list[dict]
    ) -> dict[str, Any]:
        prompt = (
            "You verify whether a proposed answer is supported by the provided Slack "
            "evidence and confirmed memory. Return JSON with keys: support_level "
            "(SUPPORTED|PARTIALLY_SUPPORTED|CONFLICTING|INSUFFICIENT_EVIDENCE), "
            "confidence (0-1), contradictions (list), missing_evidence (list), "
            "safe_to_answer (bool).\n\n"
            f"Proposed answer:\n{proposed_answer}\n\n"
            f"Evidence:\n{json.dumps(evidence_messages)}\n\n"
            f"Memory:\n{json.dumps(memory_items)}"
        )
        return self._json_or_heuristic(
            prompt,
            lambda: heuristics.verify_evidence(evidence_messages, memory_items),
        )

    def detect_conflict(
        self, new_message: str, confirmed_memory: list[dict], latest_context: str = ""
    ) -> dict[str, Any]:
        prompt = (
            "Decide whether the new Slack message contradicts confirmed memory. "
            "Return JSON with keys: is_conflict (bool), conflict_type, severity "
            "(low|medium|high), explanation, recommended_action.\n\n"
            f"New message:\n{new_message}\n\n"
            f"Confirmed memory:\n{json.dumps(confirmed_memory)}\n\n"
            f"Latest context:\n{latest_context}"
        )
        return self._json_or_heuristic(
            prompt, lambda: heuristics.detect_conflict(new_message, confirmed_memory)
        )

    # --- internals ---
    def _json_or_heuristic(self, prompt: str, fallback) -> dict[str, Any]:
        if not self._client:
            return fallback()
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                max_tokens=1024,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "You are AlignOS. Respond ONLY with a single valid JSON object.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )
            text = (resp.choices[0].message.content or "").strip()
            return json.loads(text)
        except Exception as exc:  # pragma: no cover - network/parse dependent
            logger.warning("LLM call failed (%s); falling back to heuristics.", exc)
            return fallback()


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient()
