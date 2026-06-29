"""
Unit tests for TranslationAgent and SummaryAgent.

All LLM calls (OpenRouterClient) and settings are mocked.
Three sample news articles are used as fixtures throughout.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.openrouter import ChatResult, ChatUsage
from app.modules.pipeline.summarizer import (
    SummaryAgent,
    SummaryInput,
    SummaryResult,
    _extract_summary_field,
    _has_persian,
    _parse_batch_json as summarizer_parse_batch,
    _parse_single_json as summarizer_parse_single,
    summarize_fa,
    summary_agent,
)
from app.modules.pipeline.translator import (
    TranslationAgent,
    TranslationInput,
    TranslationResult,
    _extract_field,
    _has_persian as translator_has_persian,
    _parse_batch_json as translator_parse_batch,
    _parse_single_json as translator_parse_single,
    translate_to_fa,
    translation_agent,
)


# ===========================================================================
# Sample news fixtures
# ===========================================================================

SAMPLE_EN_1 = TranslationInput(
    title="Bitcoin Hits $100,000 All-Time High",
    content=(
        "Bitcoin surged past $100,000 on Tuesday, setting a new all-time high. "
        "The rally was driven by institutional demand and spot ETF inflows. "
        "Analysts predict further upside as market sentiment remains bullish."
    ),
    source_name="CoinDesk",
    news_id=1,
)

SAMPLE_EN_2 = TranslationInput(
    title="Ethereum Layer-2 Networks See Record Activity",
    content=(
        "Ethereum's Layer-2 ecosystem hit a new milestone with over 10 million "
        "daily transactions across Arbitrum and Optimism. "
        "The surge coincided with DeFi protocol launches and reduced gas fees."
    ),
    source_name="The Block",
    news_id=2,
)

SAMPLE_EN_3 = TranslationInput(
    title="SEC Approves Bitcoin ETF Options Trading",
    content=(
        "The U.S. Securities and Exchange Commission approved options trading "
        "on spot Bitcoin ETFs. Market makers expect significant volume increase "
        "as institutional investors gain more hedging tools."
    ),
    source_name="Decrypt",
    news_id=3,
)

SAMPLE_FA_1 = SummaryInput(
    title="بیتکوین به بالاترین سطح تاریخی رسید",
    content=(
        "بیتکوین در روز سه‌شنبه از مرز ۱۰۰ هزار دلار عبور کرد و رکورد جدیدی ثبت نمود. "
        "این رشد تحت تأثیر تقاضای نهادی و ورود سرمایه به ETFهای بیت‌کوین بود. "
        "تحلیلگران انتظار دارند روند صعودی ادامه داشته باشد."
    ),
    news_id=10,
)

SAMPLE_FA_2 = SummaryInput(
    title="اتریوم رکورد جدیدی در شبکه‌های لایه دو ثبت کرد",
    content=(
        "اکوسیستم لایه دو اتریوم با بیش از ۱۰ میلیون تراکنش روزانه رکورد جدیدی ثبت کرد. "
        "شبکه‌های Arbitrum و Optimism پیشتاز این رشد بودند. "
        "کاهش کارمزد تراکنش‌ها به افزایش استفاده از پروتکل‌های DeFi کمک کرده است."
    ),
    news_id=11,
)

SAMPLE_FA_3 = SummaryInput(
    title="SEC معاملات اختیار ETF بیتکوین را تأیید کرد",
    content=(
        "کمیسیون بورس و اوراق بهادار ایالات متحده معاملات اختیار خرید و فروش "
        "بر روی ETFهای اسپات بیتکوین را تأیید کرد. "
        "این اقدام ابزارهای پوشش ریسک بیشتری در اختیار سرمایه‌گذاران نهادی قرار می‌دهد."
    ),
    news_id=12,
)


# ===========================================================================
# Settings mock helper
# ===========================================================================

def _mock_settings(model="google/gemini-flash-1.5", max_translate=2000, max_summary=150):
    mock = MagicMock()

    async def _get(key, default=None):
        return {
            "ai.fast_model": model,
            "ai.translation_max_tokens": max_translate,
            "ai.summary_max_tokens": max_summary,
        }.get(key, default)

    mock.get = _get
    return mock


def _make_result(content: str) -> ChatResult:
    return ChatResult(content=content, usage=ChatUsage(100, 50, 150), model="gemini")


# ===========================================================================
# Shared helpers (_has_persian, _extract_field)
# ===========================================================================

class TestHelpers:
    def test_has_persian_true(self):
        assert _has_persian("بیتکوین") is True
        assert translator_has_persian("امروز") is True

    def test_has_persian_false(self):
        assert _has_persian("Bitcoin") is False
        assert translator_has_persian("ETH price") is False

    def test_has_persian_mixed(self):
        assert _has_persian("Bitcoin (بیتکوین)") is True

    def test_extract_field_simple(self):
        json_str = '{"title_fa": "بیتکوین", "summary_fa": "خلاصه"}'
        assert _extract_field(json_str, "title_fa") == "بیتکوین"
        assert _extract_field(json_str, "summary_fa") == "خلاصه"

    def test_extract_field_escaped_quotes(self):
        json_str = '{"title_fa": "Bitcoin \\"ATH\\" reached"}'
        assert _extract_field(json_str, "title_fa") == 'Bitcoin "ATH" reached'

    def test_extract_field_missing_key(self):
        assert _extract_field('{"other": "val"}', "title_fa") == ""

    def test_extract_summary_field(self):
        raw = '{"summary_fa": "بیتکوین به قیمت جدیدی رسید"}'
        assert _extract_summary_field(raw) == "بیتکوین به قیمت جدیدی رسید"


# ===========================================================================
# _parse_single_json (translator)
# ===========================================================================

class TestTranslatorParseSingle:
    def test_valid_json(self):
        raw = '{"title_fa": "بیتکوین", "summary_fa": "خلاصه خبر"}'
        result = translator_parse_single(raw, SAMPLE_EN_1)
        assert result.title_fa == "بیتکوین"
        assert result.summary_fa == "خلاصه خبر"

    def test_falls_back_to_regex(self):
        raw = 'Here is the result: {"title_fa": "عنوان", "summary_fa": "خلاصه"} done.'
        result = translator_parse_single(raw, SAMPLE_EN_1)
        assert result.title_fa == "عنوان"

    def test_empty_title_uses_fallback(self):
        raw = '{"title_fa": "", "summary_fa": "خلاصه"}'
        result = translator_parse_single(raw, SAMPLE_EN_1)
        assert result.title_fa == SAMPLE_EN_1.title

    def test_non_persian_summary_becomes_empty(self):
        raw = '{"title_fa": "بیتکوین", "summary_fa": "Bitcoin reaches ATH"}'
        result = translator_parse_single(raw, SAMPLE_EN_1)
        assert result.summary_fa == ""

    def test_invalid_json_uses_regex_fallback(self):
        raw = 'title_fa: "عنوان فارسی", summary_fa: "خلاصه فارسی"'
        result = translator_parse_single(raw, SAMPLE_EN_1)
        # Should either extract via regex or use fallback
        assert result.title_fa  # not empty


# ===========================================================================
# _parse_batch_json (translator)
# ===========================================================================

class TestTranslatorParseBatch:
    def test_valid_array(self):
        raw = '[{"id": 1, "title_fa": "عنوان اول", "summary_fa": "خلاصه اول"},' \
              ' {"id": 2, "title_fa": "عنوان دوم", "summary_fa": "خلاصه دوم"}]'
        items = [SAMPLE_EN_1, SAMPLE_EN_2]
        results = translator_parse_batch(raw, items)
        assert results is not None
        assert len(results) == 2
        assert results[0].title_fa == "عنوان اول"
        assert results[1].title_fa == "عنوان دوم"

    def test_array_embedded_in_text(self):
        raw = 'Here are the results:\n[{"id": 1, "title_fa": "بیتکوین", "summary_fa": "خلاصه"}]'
        results = translator_parse_batch(raw, [SAMPLE_EN_1])
        assert results is not None
        assert results[0].title_fa == "بیتکوین"

    def test_invalid_json_returns_none(self):
        assert translator_parse_batch("not json at all", [SAMPLE_EN_1]) is None

    def test_empty_title_uses_item_fallback(self):
        raw = '[{"id": 1, "title_fa": "", "summary_fa": "خلاصه"}]'
        results = translator_parse_batch(raw, [SAMPLE_EN_1])
        assert results is not None
        assert results[0].title_fa == SAMPLE_EN_1.title

    def test_non_persian_summary_becomes_empty(self):
        raw = '[{"id": 1, "title_fa": "عنوان", "summary_fa": "English only text"}]'
        results = translator_parse_batch(raw, [SAMPLE_EN_1])
        assert results is not None
        assert results[0].summary_fa == ""


# ===========================================================================
# TranslationAgent.process_single
# ===========================================================================

@pytest.fixture
def ta() -> TranslationAgent:
    return TranslationAgent()


class TestTranslationAgentSingle:
    @pytest.mark.asyncio
    async def test_returns_translation_result(self, ta):
        llm_json = '{"title_fa": "بیتکوین ۱۰۰ هزار دلار شد", "summary_fa": "بیتکوین رکورد زد."}'

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result(llm_json))

        with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.translator.settings", _mock_settings()):
            result = await ta.process_single(SAMPLE_EN_1)

        assert isinstance(result, TranslationResult)
        assert result.title_fa == "بیتکوین ۱۰۰ هزار دلار شد"
        assert "بیتکوین" in result.summary_fa
        assert result.news_id == 1

    @pytest.mark.asyncio
    async def test_passes_source_name_to_prompt(self, ta):
        captured: dict = {}

        async def fake_chat(**kwargs):
            captured["messages"] = kwargs["messages"]
            return _make_result('{"title_fa": "عنوان", "summary_fa": "خلاصه"}')

        mock_client = MagicMock()
        mock_client.chat = fake_chat

        with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.translator.settings", _mock_settings()):
            await ta.process_single(SAMPLE_EN_1)

        user_msg = captured["messages"][1]["content"]
        assert "CoinDesk" in user_msg

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self, ta):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result("not json"))

        with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.translator.settings", _mock_settings()):
            result = await ta.process_single(SAMPLE_EN_1)

        # title_fa should fall back to original English title
        assert result.title_fa == SAMPLE_EN_1.title

    @pytest.mark.asyncio
    async def test_uses_model_from_settings(self, ta):
        captured: dict = {}

        async def fake_chat(**kwargs):
            captured["model"] = kwargs["model"]
            return _make_result('{"title_fa": "عنوان", "summary_fa": "خلاصه"}')

        mock_client = MagicMock()
        mock_client.chat = fake_chat

        with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.translator.settings", _mock_settings(model="openai/gpt-4o-mini")):
            await ta.process_single(SAMPLE_EN_1)

        assert captured["model"] == "openai/gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_three_sample_articles(self, ta):
        """Process all 3 sample EN articles, each returning valid JSON."""
        responses = [
            '{"title_fa": "بیتکوین ۱۰۰ هزار دلار شد", "summary_fa": "بیتکوین رکورد زد."}',
            '{"title_fa": "شبکه لایه دو اتریوم رکورد زد", "summary_fa": "شبکه لایه دو رشد کرد."}',
            '{"title_fa": "SEC معاملات اختیار را تأیید کرد", "summary_fa": "کمیسیون بورس تأیید داد."}',
        ]
        idx = 0

        async def rotating_chat(**kwargs):
            nonlocal idx
            r = _make_result(responses[idx % len(responses)])
            idx += 1
            return r

        mock_client = MagicMock()
        mock_client.chat = rotating_chat

        with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.translator.settings", _mock_settings()):
            r1 = await ta.process_single(SAMPLE_EN_1)
            r2 = await ta.process_single(SAMPLE_EN_2)
            r3 = await ta.process_single(SAMPLE_EN_3)

        assert r1.title_fa == "بیتکوین ۱۰۰ هزار دلار شد"
        assert r2.title_fa == "شبکه لایه دو اتریوم رکورد زد"
        assert r3.title_fa == "SEC معاملات اختیار را تأیید کرد"
        for r in (r1, r2, r3):
            assert _has_persian(r.summary_fa)


# ===========================================================================
# TranslationAgent.process_batch
# ===========================================================================

class TestTranslationAgentBatch:
    @pytest.mark.asyncio
    async def test_batch_single_item_delegates_to_process_single(self, ta):
        with patch.object(ta, "process_single", new=AsyncMock(
            return_value=TranslationResult("عنوان", "خلاصه", news_id=1)
        )) as mock_single:
            results = await ta.process_batch([SAMPLE_EN_1])

        mock_single.assert_awaited_once_with(SAMPLE_EN_1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_batch_three_items_one_call(self, ta):
        batch_json = (
            '[{"id": 1, "title_fa": "عنوان اول", "summary_fa": "خلاصه اول"},'
            ' {"id": 2, "title_fa": "عنوان دوم", "summary_fa": "خلاصه دوم"},'
            ' {"id": 3, "title_fa": "عنوان سوم", "summary_fa": "خلاصه سوم"}]'
        )
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result(batch_json))

        with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.translator.settings", _mock_settings()):
            results = await ta.process_batch([SAMPLE_EN_1, SAMPLE_EN_2, SAMPLE_EN_3])

        # Only one LLM call for all three items
        assert mock_client.chat.await_count == 1
        assert len(results) == 3
        assert results[0].title_fa == "عنوان اول"
        assert results[2].title_fa == "عنوان سوم"

    @pytest.mark.asyncio
    async def test_batch_falls_back_on_parse_failure(self, ta):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result("not parseable"))

        single_result = TranslationResult("عنوان", "خلاصه")

        with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.translator.settings", _mock_settings()), \
             patch.object(ta, "process_single", new=AsyncMock(return_value=single_result)) as mock_s:
            results = await ta.process_batch([SAMPLE_EN_1, SAMPLE_EN_2])

        # Batch failed → falls back to 2 individual calls
        assert mock_s.await_count == 2
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_batch_empty_list(self, ta):
        results = await ta.process_batch([])
        assert results == []


# ===========================================================================
# Backward-compat translate_to_fa
# ===========================================================================

@pytest.mark.asyncio
async def test_translate_to_fa_returns_tuple():
    llm_json = '{"title_fa": "عنوان فارسی", "summary_fa": "خلاصه فارسی"}'
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=_make_result(llm_json))

    with patch("app.modules.pipeline.translator.get_client", return_value=mock_client), \
         patch("app.modules.pipeline.translator.settings", _mock_settings()):
        title_fa, summary_fa = await translate_to_fa("BTC title", "BTC content", news_id=5)

    assert title_fa == "عنوان فارسی"
    assert summary_fa == "خلاصه فارسی"


# ===========================================================================
# _parse_single_json (summarizer)
# ===========================================================================

class TestSummarizerParseSingle:
    def test_valid_json(self):
        raw = '{"summary_fa": "بیتکوین امروز رشد کرد."}'
        assert summarizer_parse_single(raw) == "بیتکوین امروز رشد کرد."

    def test_regex_fallback(self):
        raw = 'result: {"summary_fa": "خلاصه خبر کریپتو"} end'
        assert summarizer_parse_single(raw) == "خلاصه خبر کریپتو"

    def test_completely_invalid_returns_empty(self):
        assert summarizer_parse_single("no json here at all") == ""

    def test_empty_summary_returns_empty(self):
        assert summarizer_parse_single('{"summary_fa": ""}') == ""


# ===========================================================================
# _parse_batch_json (summarizer)
# ===========================================================================

class TestSummarizerParseBatch:
    def test_valid_array(self):
        raw = '[{"id": 1, "summary_fa": "خلاصه اول"}, {"id": 2, "summary_fa": "خلاصه دوم"}]'
        items = [SAMPLE_FA_1, SAMPLE_FA_2]
        results = summarizer_parse_batch(raw, items)
        assert results is not None
        assert results[0].summary_fa == "خلاصه اول"
        assert results[1].summary_fa == "خلاصه دوم"

    def test_invalid_returns_none(self):
        assert summarizer_parse_batch("garbage", [SAMPLE_FA_1]) is None

    def test_non_persian_summary_becomes_empty(self):
        raw = '[{"id": 1, "summary_fa": "English summary here"}]'
        results = summarizer_parse_batch(raw, [SAMPLE_FA_1])
        assert results is not None
        assert results[0].summary_fa == ""


# ===========================================================================
# SummaryAgent.process_single
# ===========================================================================

@pytest.fixture
def sa() -> SummaryAgent:
    return SummaryAgent()


class TestSummaryAgentSingle:
    @pytest.mark.asyncio
    async def test_returns_summary_result(self, sa):
        llm_json = '{"summary_fa": "بیتکوین به بالاترین قیمت تاریخی رسید."}'
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result(llm_json))

        with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.summarizer.settings", _mock_settings()):
            result = await sa.process_single(SAMPLE_FA_1)

        assert isinstance(result, SummaryResult)
        assert _has_persian(result.summary_fa)
        assert result.news_id == 10

    @pytest.mark.asyncio
    async def test_non_persian_summary_becomes_empty(self, sa):
        llm_json = '{"summary_fa": "Bitcoin reached ATH today"}'
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result(llm_json))

        with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.summarizer.settings", _mock_settings()):
            result = await sa.process_single(SAMPLE_FA_1)

        assert result.summary_fa == ""

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self, sa):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result("not json"))

        with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.summarizer.settings", _mock_settings()):
            result = await sa.process_single(SAMPLE_FA_1)

        assert isinstance(result, SummaryResult)
        # summary_fa may be empty but no exception raised
        assert isinstance(result.summary_fa, str)

    @pytest.mark.asyncio
    async def test_three_sample_fa_articles(self, sa):
        """Summarise all 3 sample FA articles."""
        responses = [
            '{"summary_fa": "بیتکوین رکورد زد."}',
            '{"summary_fa": "شبکه لایه دو رشد کرد."}',
            '{"summary_fa": "معاملات اختیار تأیید شد."}',
        ]
        idx = 0

        async def rotating_chat(**kwargs):
            nonlocal idx
            r = _make_result(responses[idx % len(responses)])
            idx += 1
            return r

        mock_client = MagicMock()
        mock_client.chat = rotating_chat

        with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.summarizer.settings", _mock_settings()):
            r1 = await sa.process_single(SAMPLE_FA_1)
            r2 = await sa.process_single(SAMPLE_FA_2)
            r3 = await sa.process_single(SAMPLE_FA_3)

        for r in (r1, r2, r3):
            assert _has_persian(r.summary_fa)


# ===========================================================================
# SummaryAgent.process_batch
# ===========================================================================

class TestSummaryAgentBatch:
    @pytest.mark.asyncio
    async def test_batch_single_item_delegates_to_process_single(self, sa):
        with patch.object(sa, "process_single", new=AsyncMock(
            return_value=SummaryResult("خلاصه", news_id=10)
        )) as mock_s:
            results = await sa.process_batch([SAMPLE_FA_1])

        mock_s.assert_awaited_once_with(SAMPLE_FA_1)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_batch_three_fa_articles_one_call(self, sa):
        batch_json = (
            '[{"id": 1, "summary_fa": "خلاصه اول"},'
            ' {"id": 2, "summary_fa": "خلاصه دوم"},'
            ' {"id": 3, "summary_fa": "خلاصه سوم"}]'
        )
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result(batch_json))

        with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.summarizer.settings", _mock_settings()):
            results = await sa.process_batch([SAMPLE_FA_1, SAMPLE_FA_2, SAMPLE_FA_3])

        assert mock_client.chat.await_count == 1
        assert len(results) == 3
        assert results[0].summary_fa == "خلاصه اول"

    @pytest.mark.asyncio
    async def test_batch_falls_back_on_parse_failure(self, sa):
        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=_make_result("not parseable"))

        with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.summarizer.settings", _mock_settings()), \
             patch.object(sa, "process_single", new=AsyncMock(
                 return_value=SummaryResult("خلاصه")
             )) as mock_s:
            results = await sa.process_batch([SAMPLE_FA_1, SAMPLE_FA_2])

        assert mock_s.await_count == 2

    @pytest.mark.asyncio
    async def test_batch_empty_list(self, sa):
        results = await sa.process_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_batch_max_tokens_scales_with_count(self, sa):
        """max_tokens should be N * summary_max_tokens for batch."""
        captured: dict = {}

        async def fake_chat(**kwargs):
            captured["max_tokens"] = kwargs["max_tokens"]
            return _make_result('[{"id": 1, "summary_fa": "خلاصه"},'
                                ' {"id": 2, "summary_fa": "خلاصه"},'
                                ' {"id": 3, "summary_fa": "خلاصه"}]')

        mock_client = MagicMock()
        mock_client.chat = fake_chat

        with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
             patch("app.modules.pipeline.summarizer.settings",
                   _mock_settings(max_summary=100)):
            await sa.process_batch([SAMPLE_FA_1, SAMPLE_FA_2, SAMPLE_FA_3])

        # 3 items × 100 tokens = 300
        assert captured["max_tokens"] == 300


# ===========================================================================
# Backward-compat summarize_fa
# ===========================================================================

@pytest.mark.asyncio
async def test_summarize_fa_returns_string():
    llm_json = '{"summary_fa": "خلاصه خبر کریپتو"}'
    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=_make_result(llm_json))

    with patch("app.modules.pipeline.summarizer.get_client", return_value=mock_client), \
         patch("app.modules.pipeline.summarizer.settings", _mock_settings()):
        result = await summarize_fa("محتوا", news_id=99, title="عنوان")

    assert result == "خلاصه خبر کریپتو"


# ===========================================================================
# Singletons
# ===========================================================================

def test_translation_agent_singleton():
    assert isinstance(translation_agent, TranslationAgent)


def test_summary_agent_singleton():
    assert isinstance(summary_agent, SummaryAgent)
