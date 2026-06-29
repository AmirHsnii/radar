"""Build the text used for category/coin embedding classification."""
from __future__ import annotations

from app.config import settings


async def build_classify_text(
    *,
    title_fa: str | None = None,
    summary_fa: str | None = None,
    content: str | None = None,
    raw_title: str | None = None,
) -> str:
    """
    Combine processed and raw fields for classifier input.

    Order: Persian title → Persian summary → raw title → content excerpt.
    Embedding models see title + summary (LLM output) plus a content snippet
    so coin mentions in the body are not lost when the summary is short.
    """
    max_chars = int(await settings.get("classifier.max_classify_chars", 1500))
    content_chars = int(await settings.get("classifier.content_snippet_chars", 800))

    parts: list[str] = []
    for chunk in (title_fa, summary_fa, raw_title):
        text = (chunk or "").strip()
        if text and text not in parts:
            parts.append(text)

    body = (content or "").strip()
    if body:
        parts.append(body[:content_chars])

    combined = " ".join(parts).strip()
    return combined[:max_chars]
