"""
SummaryAgent — summarises Persian crypto news into 2–3 sentences.

Used for FA sources (articles that do not need translation).

System prompt is taken verbatim from AGENTS.md §Agent 2B.

Batch mode: all items sent in a single LLM call to minimise cost.
Falls back to per-item calls if batch JSON parsing fails completely.

Validation: summary_fa must contain Persian characters.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import structlog

from app.config import settings
from app.core.openrouter import get_agent_client, get_agent_model
from app.modules.pipeline.prompts import get_agent_prompt

log = structlog.get_logger(__name__)

_FA_RE = re.compile(r"[؀-ۿ]")
_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)


# ---------------------------------------------------------------------------
# System prompt loaded from settings (see prompts.py)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SummaryInput:
    title: str
    content: str
    news_id: int | None = None
    prompt_agent: str = "summarizer"


@dataclass
class SummaryResult:
    summary_fa: str
    news_id: int | None = None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _has_persian(text: str) -> bool:
    return bool(_FA_RE.search(text))


def _extract_summary_field(text: str) -> str:
    m = re.search(r'"summary_fa"\s*:\s*"((?:[^"\\]|\\.)*)"', text, re.DOTALL)
    if not m:
        return ""
    return m.group(1).replace('\\"', '"').replace("\\n", "\n").strip()


def _parse_single_json(raw: str) -> str:
    """
    Extract summary_fa from LLM output.
    1. json.loads()
    2. Regex extraction
    3. Returns empty string on complete failure.
    """
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            val = (data.get("summary_fa") or "").strip()
            if val:
                return val
    except json.JSONDecodeError:
        log.debug("summarizer.json_parse_failed_trying_regex")

    return _extract_summary_field(raw)


def _parse_batch_json(raw: str, items: list[SummaryInput]) -> list[SummaryResult] | None:
    """
    Parse JSON array response for batch summarisation.
    Returns None on complete failure (caller falls back to single calls).
    """
    array_match = _ARRAY_RE.search(raw)
    if not array_match:
        return None

    try:
        data = json.loads(array_match.group())
    except json.JSONDecodeError:
        return None

    if not isinstance(data, list):
        return None

    results: list[SummaryResult] = []
    for i, item in enumerate(items):
        entry = next(
            (d for d in data if isinstance(d, dict) and d.get("id") == i + 1),
            data[i] if i < len(data) else None,
        )
        summary = ""
        if entry and isinstance(entry, dict):
            summary = (entry.get("summary_fa") or "").strip()
            if summary and not _has_persian(summary):
                summary = ""

        results.append(SummaryResult(summary_fa=summary, news_id=item.news_id))

    return results


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SummaryAgent:
    """
    Summarises a Persian (or translated) crypto news article.

    process_single() — one LLM call per item
    process_batch()  — one LLM call for all items (cheaper)
    """

    async def process_single(self, item: SummaryInput) -> SummaryResult:
        """Summarise a single news item."""
        agent = item.prompt_agent or "summarizer"
        model = await get_agent_model(agent)
        max_tokens = int(await settings.get("ai.summary_max_tokens", 150))

        user_msg = f"عنوان: {item.title}\n\nمتن:\n{item.content[:4000]}"

        client = await get_agent_client(agent)
        system_prompt = await get_agent_prompt(agent)
        result = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f'{user_msg}\n\n'
                        'فرمت خروجی: {"summary_fa": "..."}'
                    ),
                },
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            task_name="summarize",
            news_id=item.news_id,
            response_format={"type": "json_object"},
        )

        summary = _parse_single_json(result.content)

        if summary and not _has_persian(summary):
            log.debug("summarizer.summary_not_persian", preview=summary[:50])
            summary = ""

        log.debug(
            "summarizer.single_done",
            news_id=item.news_id,
            has_summary=bool(summary),
        )
        return SummaryResult(summary_fa=summary, news_id=item.news_id)

    async def process_batch(
        self, items: list[SummaryInput]
    ) -> list[SummaryResult]:
        """
        Summarise multiple items in a single LLM call.
        Falls back to individual calls if the batch response cannot be parsed.
        """
        if not items:
            return []
        if len(items) == 1:
            return [await self.process_single(items[0])]

        model = await get_agent_model("summarizer")
        max_tokens = int(await settings.get("ai.summary_max_tokens", 150)) * len(items)

        per_item_content = 1000

        formatted = "\n\n".join(
            f"خبر {i + 1}:\nعنوان: {it.title}\nمتن: {it.content[:per_item_content]}"
            for i, it in enumerate(items)
        )

        batch_user_msg = (
            f"خلاصه‌ای از هر یک از این {len(items)} خبر بنویس:\n\n"
            f"{formatted}\n\n"
            "فرمت خروجی (آرایه JSON):\n"
            '[{"id": 1, "summary_fa": "..."}, ...]'
        )

        agent = items[0].prompt_agent or "summarizer"
        client = await get_agent_client(agent)
        system_prompt = await get_agent_prompt(agent)
        result = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": batch_user_msg},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            task_name="summarize_batch",
        )

        parsed = _parse_batch_json(result.content, items)
        if parsed is None:
            log.warning(
                "summarizer.batch_parse_failed_falling_back",
                count=len(items),
            )
            return [await self.process_single(item) for item in items]

        log.debug("summarizer.batch_done", count=len(items))
        return parsed


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

summary_agent = SummaryAgent()


# ---------------------------------------------------------------------------
# Backward-compatible function (used by orchestrator)
# ---------------------------------------------------------------------------

async def summarize_fa(content_fa: str, news_id: int | None = None, title: str = "") -> str:
    """Returns summary_fa string."""
    result = await summary_agent.process_single(
        SummaryInput(title=title, content=content_fa, news_id=news_id)
    )
    return result.summary_fa
