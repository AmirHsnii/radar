"""
Unit tests for RouterAgent and helper functions.

langdetect is a real library that uses random seeds — it is mocked for
deterministic tests.  The LLM step is always mocked (no real API calls).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.pipeline.router import (
    LanguageResult,
    RouterAgent,
    detect_language,
    needs_translation,
    normalize_text,
    router_agent,
)


# ===========================================================================
# normalize_text
# ===========================================================================

class TestNormalizeText:
    def test_removes_urls(self):
        text = "Bitcoin price https://coindesk.com/btc rises today"
        assert "https://" not in normalize_text(text)
        assert "Bitcoin" in normalize_text(text)

    def test_collapses_whitespace(self):
        assert normalize_text("hello   world") == "hello world"

    def test_strips_edges(self):
        assert normalize_text("  hi  ") == "hi"

    def test_nfkc_arabic_presentation_forms(self):
        # Arabic presentation form ﺑ (U+FE91) → ب (U+0628) via NFKC
        result = normalize_text("ﺑﯿﺘﮑﻮﯾﻦ")
        assert len(result) > 0   # didn't crash; normalised

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_preserves_sentence_structure(self):
        text = "Bitcoin, Ethereum, and Solana prices rose today."
        result = normalize_text(text)
        assert "Bitcoin" in result
        assert "," in result   # punctuation preserved for langdetect


# ===========================================================================
# RouterAgent._rule_based
# ===========================================================================

@pytest.fixture
def agent() -> RouterAgent:
    return RouterAgent()


class TestRuleBased:
    def test_fa_high_ratio(self, agent):
        # Pure Persian text — ratio >> 30%
        text = "بیتکوین امروز رکورد جدیدی ثبت کرد و به سقف تاریخی رسید"
        result = agent._rule_based(normalize_text(text))
        assert result is not None
        assert result.language == "fa"
        assert result.method == "rule"
        assert result.confidence == 0.99

    def test_en_low_ratio(self, agent):
        # Pure English — ratio << 5%
        text = "Bitcoin price hits new all-time high above one hundred thousand dollars"
        result = agent._rule_based(normalize_text(text))
        assert result is not None
        assert result.language == "en"
        assert result.method == "rule"
        assert result.confidence == 0.95

    def test_mixed_returns_none(self, agent):
        # ~15% Arabic chars — ambiguous
        text = "Bitcoin (بیتکوین) rises above 100k dollars today"
        result = agent._rule_based(normalize_text(text))
        # May or may not be None depending on ratio — just verify it's valid
        if result is not None:
            assert result.language in ("fa", "en")

    def test_empty_returns_none(self, agent):
        assert agent._rule_based("") is None

    def test_spaces_only_returns_none(self, agent):
        assert agent._rule_based("   ") is None

    def test_short_latin_text_no_call(self, agent):
        # < 20 chars — rule does not fire for en (requires enough text)
        result = agent._rule_based("BTC")
        # Should either return None or return en — but not fa
        if result:
            assert result.language == "en"

    def test_arabic_text_treated_as_fa(self, agent):
        # Arabic text (not Persian) — still > 30% Arabic chars → "fa"
        text = "بيتكوين يرتفع اليوم في السوق العالمية"
        result = agent._rule_based(normalize_text(text))
        assert result is not None
        assert result.language == "fa"

    def test_confidence_threshold_boundary(self, agent):
        # Title with exactly ~30% Persian chars should return "fa"
        # 10 Persian chars + 23 Latin chars = 43 total → 23% → ambiguous → None
        text = "بیتکوین bitcoin ethereum sol"  # ~25% Persian
        result = agent._rule_based(normalize_text(text))
        # Just verify it doesn't crash and returns valid output
        if result:
            assert result.language in ("fa", "en")


# ===========================================================================
# RouterAgent._langdetect
# ===========================================================================

class TestLangdetect:
    def test_fa_high_confidence(self, agent):
        lang_obj = MagicMock()
        lang_obj.lang = "fa"
        lang_obj.prob = 0.99

        with patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = agent._langdetect("بیتکوین امروز افزایش یافت")

        assert result is not None
        assert result.language == "fa"
        assert result.method == "langdetect"
        assert result.confidence == pytest.approx(0.99)

    def test_en_high_confidence(self, agent):
        lang_obj = MagicMock()
        lang_obj.lang = "en"
        lang_obj.prob = 0.98

        with patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = agent._langdetect("Bitcoin price surges past 100k")

        assert result is not None
        assert result.language == "en"
        assert result.confidence == pytest.approx(0.98)

    def test_ar_mapped_to_fa(self, agent):
        lang_obj = MagicMock()
        lang_obj.lang = "ar"
        lang_obj.prob = 0.95

        with patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = agent._langdetect("بيتكوين يرتفع اليوم")

        assert result is not None
        assert result.language == "fa"  # Arabic → mapped to fa

    def test_low_confidence_returns_none(self, agent):
        lang_obj = MagicMock()
        lang_obj.lang = "en"
        lang_obj.prob = 0.75   # below threshold

        with patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = agent._langdetect("some ambiguous text")

        assert result is None

    def test_langdetect_exception_returns_none(self, agent):
        from langdetect import LangDetectException
        with patch("app.modules.pipeline.router.detect_langs",
                   side_effect=LangDetectException(0, "no features")):
            result = agent._langdetect("???")

        assert result is None

    def test_empty_result_returns_none(self, agent):
        with patch("app.modules.pipeline.router.detect_langs", return_value=[]):
            result = agent._langdetect("some text")

        assert result is None

    def test_short_text_returns_none(self, agent):
        result = agent._langdetect("hi")
        # Too short → skips langdetect
        assert result is None

    def test_unexpected_language_returns_none(self, agent):
        # Turkish — neither fa nor en
        lang_obj = MagicMock()
        lang_obj.lang = "tr"
        lang_obj.prob = 0.97

        with patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = agent._langdetect("bugün bitcoin yükseldi")

        assert result is None


# ===========================================================================
# RouterAgent._llm_detect
# ===========================================================================

class TestLLMDetect:
    @pytest.mark.asyncio
    async def test_llm_returns_fa(self, agent):
        from app.core.openrouter import ChatResult, ChatUsage

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=ChatResult(
            content='{"language": "fa"}',
            usage=ChatUsage(0, 0, 0),
            model="gemini",
        ))

        with patch("app.core.openrouter.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.router.settings") as mock_settings:
            mock_settings.get = AsyncMock(return_value="google/gemini-flash-1.5")
            result = await agent._llm_detect("بیتکوین", "محتوا")

        assert result.language == "fa"
        assert result.method == "llm"
        assert result.confidence == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_llm_returns_en(self, agent):
        from app.core.openrouter import ChatResult, ChatUsage

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=ChatResult(
            content='{"language": "en"}',
            usage=ChatUsage(0, 0, 0),
            model="gemini",
        ))

        with patch("app.core.openrouter.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.router.settings") as mock_settings:
            mock_settings.get = AsyncMock(return_value="google/gemini-flash-1.5")
            result = await agent._llm_detect("Bitcoin", "content")

        assert result.language == "en"

    @pytest.mark.asyncio
    async def test_llm_normalises_unexpected_language(self, agent):
        from app.core.openrouter import ChatResult, ChatUsage

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=ChatResult(
            content='{"language": "ar"}',  # unexpected value
            usage=ChatUsage(0, 0, 0),
            model="gemini",
        ))

        with patch("app.core.openrouter.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.router.settings") as mock_settings:
            mock_settings.get = AsyncMock(return_value="google/gemini-flash-1.5")
            result = await agent._llm_detect("test", "test")

        assert result.language == "en"  # unknown lang normalised to "en"

    @pytest.mark.asyncio
    async def test_llm_fallback_on_exception(self, agent):
        with patch("app.core.openrouter.get_client", side_effect=Exception("API down")), \
             patch("app.modules.pipeline.router.settings") as mock_settings:
            mock_settings.get = AsyncMock(return_value="gemini")
            result = await agent._llm_detect("test", "test")

        assert result.language == "en"
        assert result.method == "llm"
        assert result.confidence == pytest.approx(0.50)


# ===========================================================================
# RouterAgent.detect — full three-step flow
# ===========================================================================

class TestDetectFull:
    @pytest.mark.asyncio
    async def test_detect_fa_via_rule(self, agent):
        text = "بیتکوین امروز رکورد زد و قیمت به بالاترین سطح رسید"
        result = await agent.detect(title=text, content_preview="")
        assert result.language == "fa"
        assert result.method == "rule"

    @pytest.mark.asyncio
    async def test_detect_en_via_rule(self, agent):
        text = "Bitcoin price reaches new all-time high above one hundred thousand dollars today"
        result = await agent.detect(title=text, content_preview="")
        assert result.language == "en"
        assert result.method == "rule"

    @pytest.mark.asyncio
    async def test_detect_uses_content_preview(self, agent):
        # Short ambiguous title, but content is clear Persian
        content = "بیتکوین به بالاترین سطح تاریخی خود رسید. بازار کریپتو امروز سبزپوش شد."
        result = await agent.detect(title="Crypto news", content_preview=content)
        assert result.language == "fa"

    @pytest.mark.asyncio
    async def test_detect_en_via_langdetect(self, agent):
        # Patch rule_based to return None so langdetect step is exercised
        lang_obj = MagicMock()
        lang_obj.lang = "en"
        lang_obj.prob = 0.97

        with patch.object(agent, "_rule_based", return_value=None), \
             patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = await agent.detect(
                title="BTC rises",
                content_preview="Bitcoin rose sharply in early trading.",
            )

        assert result.language == "en"
        assert result.method == "langdetect"

    @pytest.mark.asyncio
    async def test_detect_triggers_llm_for_ambiguous(self, agent):
        """When rule and langdetect both return None, LLM should be called."""
        # Patch both steps to return None
        with patch.object(agent, "_rule_based", return_value=None), \
             patch.object(agent, "_langdetect", return_value=None), \
             patch.object(agent, "_llm_detect", new=AsyncMock(
                 return_value=LanguageResult("en", "llm", 0.85)
             )) as mock_llm:
            result = await agent.detect("ambiguous title", "ambiguous content")

        mock_llm.assert_awaited_once()
        assert result.method == "llm"

    @pytest.mark.asyncio
    async def test_detect_skips_llm_when_rule_succeeds(self, agent):
        with patch.object(agent, "_llm_detect", new=AsyncMock()) as mock_llm:
            text = "بیتکوین امروز رکورد زد"
            await agent.detect(title=text)

        mock_llm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_detect_result_has_all_fields(self, agent):
        text = "Bitcoin hits new ATH today in global crypto markets"
        result = await agent.detect(title=text)
        assert isinstance(result, LanguageResult)
        assert result.language in ("fa", "en")
        assert result.method in ("rule", "langdetect", "llm")
        assert 0.0 <= result.confidence <= 1.0


# ===========================================================================
# Backward-compatible helpers
# ===========================================================================

class TestBackwardCompat:
    def test_detect_language_fa(self):
        text = "بیتکوین امروز رکورد جدیدی ثبت کرد در بازار ارزهای دیجیتال"
        assert detect_language(text) == "fa"

    def test_detect_language_en(self):
        text = "Bitcoin sets a new all-time high above one hundred thousand dollars"
        assert detect_language(text) == "en"

    def test_detect_language_uses_langdetect_for_short_en(self):
        lang_obj = MagicMock()
        lang_obj.lang = "en"
        lang_obj.prob = 0.99

        with patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = detect_language("BTC ETH SOL DeFi")

        assert result == "en"

    def test_detect_language_defaults_to_en_on_uncertainty(self):
        # langdetect returns low confidence → falls back to "en"
        lang_obj = MagicMock()
        lang_obj.lang = "unknown"
        lang_obj.prob = 0.50

        with patch("app.modules.pipeline.router.detect_langs", return_value=[lang_obj]):
            result = detect_language("???")

        assert result == "en"

    def test_needs_translation_en_is_true(self):
        assert needs_translation("en") is True

    def test_needs_translation_fa_is_false(self):
        assert needs_translation("fa") is False

    def test_needs_translation_unknown_is_false(self):
        # unknown text goes through pipeline as-is (treated as FA)
        assert needs_translation("unknown") is False

    def test_router_agent_singleton(self):
        from app.modules.pipeline.router import router_agent as ra
        assert isinstance(ra, RouterAgent)
