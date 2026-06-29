"""Tests for content resolution and WP summary-only label."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.news import GENERATION_MODE_FULL, GENERATION_MODE_SUMMARY_ONLY
from app.modules.crawler.content_resolve import resolve_article_content
from app.modules.publisher.wordpress import SUMMARY_ONLY_LABEL_FA, _build_content


@pytest.mark.asyncio
async def test_resolve_uses_fetched_content():
    item = MagicMock()
    item.content = None
    item.title = "Title"
    item.url = "https://example.com/a"

    with patch(
        "app.modules.crawler.content_resolve.fetch_content",
        AsyncMock(return_value="Full article body"),
    ):
        text, mode = await resolve_article_content(item)

    assert text == "Full article body"
    assert mode == GENERATION_MODE_FULL
    assert item.content == "Full article body"


@pytest.mark.asyncio
async def test_resolve_falls_back_to_title_summary_only():
    item = MagicMock()
    item.content = None
    item.title = "Bitcoin rises"
    item.url = "https://example.com/a"
    item.generation_mode = None

    with patch(
        "app.modules.crawler.content_resolve.fetch_content",
        AsyncMock(return_value=""),
    ):
        text, mode = await resolve_article_content(item)

    assert text == "Bitcoin rises"
    assert mode == GENERATION_MODE_SUMMARY_ONLY
    assert item.content is None


def test_build_content_includes_notice_when_summary_only():
    html = _build_content("خلاصه خبر", summary_only=True)
    assert SUMMARY_ONLY_LABEL_FA in html
    assert "خلاصه خبر" in html
    assert "radar-auto-summary-notice" in html


def test_build_content_no_notice_for_full():
    html = _build_content("خلاصه خبر", summary_only=False)
    assert SUMMARY_ONLY_LABEL_FA not in html
    assert html == "<p>خلاصه خبر</p>"
