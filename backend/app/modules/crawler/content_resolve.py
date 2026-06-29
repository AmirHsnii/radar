"""Resolve article body for the pipeline — page extract or title-only fallback."""
from __future__ import annotations

from app.models.news import GENERATION_MODE_FULL, GENERATION_MODE_SUMMARY_ONLY, NewsItem
from app.modules.crawler.content_fetcher import fetch_content


async def resolve_article_content(item: NewsItem) -> tuple[str, str]:
    """
    Fetch full page text when missing; fall back to title-only.

    Returns (text_for_pipeline, generation_mode).
    """
    existing = (item.content or "").strip()
    if existing:
        mode = item.generation_mode or GENERATION_MODE_FULL
        return existing, mode

    fetched = (await fetch_content(item.url)).strip()
    if fetched:
        item.content = fetched
        return fetched, GENERATION_MODE_FULL

    item.content = None
    fallback = (item.title or "").strip()
    return fallback, GENERATION_MODE_SUMMARY_ONLY
