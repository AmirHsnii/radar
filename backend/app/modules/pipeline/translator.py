"""
TranslationAgent — translates English crypto news to Persian.

Produces:
  • title_fa   — Persian title
  • summary_fa — 2–3 sentence Persian summary

System prompt is taken verbatim from AGENTS.md §Agent 2A.

Batch mode: all items sent in a single LLM call to minimise cost.
Falls back to per-item calls if batch JSON parsing fails completely.

JSON parsing strategy:
  1. json.loads() on raw LLM output
  2. Regex extraction of individual fields
  3. Validation: title_fa non-empty, summary_fa contains Persian chars
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog

from app.config import settings
from app.core.openrouter import get_agent_client, get_agent_model
from app.modules.pipeline.prompts import get_agent_prompt

log = structlog.get_logger(__name__)

_FA_RE = re.compile(r"[؀-ۿ]")            # Arabic/Persian unicode block
_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)  # find JSON array in text


# ---------------------------------------------------------------------------
# System prompt loaded from settings (see prompts.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TranslationInput:
    title: str
    content: str
    source_name: str = ""
    news_id: int | None = None


@dataclass
class TranslationResult:
    title_fa: str
    summary_fa: str
    news_id: int | None = None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _has_persian(text: str) -> bool:
    return bool(_FA_RE.search(text))


def _extract_field(text: str, field_name: str) -> str:
    """Regex fallback for a single JSON string field."""
    m = re.search(
        rf'"{re.escape(field_name)}"\s*:\s*"((?:[^"\\]|\\.)*)"',
        text, re.DOTALL,
    )
    if not m:
        return ""
    return m.group(1).replace('\\"', '"').replace("\\n", "\n").strip()


def _parse_single_json(raw: str, fallback: TranslationInput) -> TranslationResult:
    """
    Parse a single-object LLM response.
    1. json.loads()
    2. Regex field extraction
    3. Returns fallback title if title_fa is empty.
    """
    title_fa = ""
    summary_fa = ""

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            title_fa = (data.get("title_fa") or "").strip()
            summary_fa = (data.get("summary_fa") or "").strip()
    except json.JSONDecodeError:
        log.debug("translator.json_parse_failed_trying_regex")
        title_fa = _extract_field(raw, "title_fa")
        summary_fa = _extract_field(raw, "summary_fa")

    if not title_fa:
        log.debug("translator.empty_title_fa_using_fallback")
        title_fa = fallback.title

    if summary_fa and not _has_persian(summary_fa):
        log.debug("translator.summary_not_persian", summary_preview=summary_fa[:50])
        summary_fa = ""

    return TranslationResult(
        title_fa=title_fa,
        summary_fa=summary_fa,
        news_id=fallback.news_id,
    )


def _parse_batch_json(raw: str, items: list[TranslationInput]) -> list[TranslationResult] | None:
    """
    Parse a JSON array response for batch translation.
    Returns None if parsing fails completely (caller should fallback to single calls).
    """
    # Try to find a JSON array anywhere in the response
    array_match = _ARRAY_RE.search(raw)
    if not array_match:
        return None

    try:
        data = json.loads(array_match.group())
    except json.JSONDecodeError:
        return None

    if not isinstance(data, list):
        return None

    results: list[TranslationResult] = []
    for i, item in enumerate(items):
        # Match by 1-based id field if present, else by position
        entry = next(
            (d for d in data if isinstance(d, dict) and d.get("id") == i + 1),
            data[i] if i < len(data) else None,
        )
        if entry and isinstance(entry, dict):
            title_fa = (entry.get("title_fa") or "").strip() or item.title
            summary_fa = (entry.get("summary_fa") or "").strip()
            if summary_fa and not _has_persian(summary_fa):
                summary_fa = ""
            results.append(TranslationResult(
                title_fa=title_fa, summary_fa=summary_fa, news_id=item.news_id
            ))
        else:
            results.append(TranslationResult(
                title_fa=item.title, summary_fa="", news_id=item.news_id
            ))

    return results


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class TranslationAgent:
    """
    Translates English crypto news to Persian and produces a brief summary.

    process_single() — one LLM call per item
    process_batch()  — one LLM call for all items (cheaper)
    """

    async def process_single(self, item: TranslationInput) -> TranslationResult:
        """Translate and summarise a single news item."""
        model = await get_agent_model("translator")
        max_tokens = int(await settings.get("ai.translation_max_tokens", 2000))

        user_msg = (
            f"Title: {item.title}\n"
            f"Content:\n{item.content[:3000]}"
        )
        if item.source_name:
            user_msg = f"Source: {item.source_name}\n" + user_msg

        client = await get_agent_client("translator")
        system_prompt = await get_agent_prompt("translator")
        result = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            task_name="translation",
            news_id=item.news_id,
            response_format={"type": "json_object"},
        )

        parsed = _parse_single_json(result.content, item)
        log.debug(
            "translator.single_done",
            news_id=item.news_id,
            has_summary=bool(parsed.summary_fa),
        )
        return parsed

    async def process_batch(
        self, items: list[TranslationInput]
    ) -> list[TranslationResult]:
        """
        Translate multiple items in a single LLM call.
        Falls back to individual calls if the batch response cannot be parsed.
        """
        if not items:
            return []
        if len(items) == 1:
            return [await self.process_single(items[0])]

        model = await get_agent_model("translator")
        # Allow enough tokens for N summaries
        max_tokens = int(await settings.get("ai.translation_max_tokens", 2000))

        # Truncate content per item so the batch fits in context
        per_item_content = 800

        formatted = "\n\n".join(
            f"Article {i + 1}:"
            + (f"\nSource: {it.source_name}" if it.source_name else "")
            + f"\nTitle: {it.title}"
            + f"\nContent: {it.content[:per_item_content]}"
            for i, it in enumerate(items)
        )

        batch_user_msg = (
            f"Translate and summarize these {len(items)} news articles:\n\n"
            f"{formatted}\n\n"
            "Return a JSON array:\n"
            '[{"id": 1, "title_fa": "...", "summary_fa": "..."}, ...]'
        )

        client = await get_agent_client("translator")
        system_prompt = await get_agent_prompt("translator")
        result = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": batch_user_msg},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            task_name="translation_batch",
        )

        parsed = _parse_batch_json(result.content, items)
        if parsed is None:
            log.warning(
                "translator.batch_parse_failed_falling_back",
                count=len(items),
            )
            return [await self.process_single(item) for item in items]

        log.debug("translator.batch_done", count=len(items))
        return parsed


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

translation_agent = TranslationAgent()


# ---------------------------------------------------------------------------
# Backward-compatible function (used by orchestrator)
# ---------------------------------------------------------------------------

async def translate_to_fa(
    title: str,
    content: str,
    news_id: int | None = None,
    source_name: str = "",
) -> tuple[str, str]:
    """Returns (title_fa, summary_fa)."""
    result = await translation_agent.process_single(
        TranslationInput(title=title, content=content,
                         source_name=source_name, news_id=news_id)
    )
    return result.title_fa, result.summary_fa
