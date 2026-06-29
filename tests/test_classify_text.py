"""Tests for classify text builder."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.modules.pipeline.classify_text import build_classify_text


@pytest.mark.asyncio
async def test_includes_title_summary_content_and_raw_title():
    with patch("app.modules.pipeline.classify_text.settings") as ms:
        ms.get = AsyncMock(side_effect=lambda k, d=None: {
            "classifier.max_classify_chars": 2000,
            "classifier.content_snippet_chars": 500,
        }.get(k, d))

        text = await build_classify_text(
            title_fa="عنوان فارسی",
            summary_fa="خلاصه",
            content="بدنه خبر " * 100,
            raw_title="English Title",
        )

    assert "عنوان فارسی" in text
    assert "خلاصه" in text
    assert "English Title" in text
    assert "بدنه خبر" in text
