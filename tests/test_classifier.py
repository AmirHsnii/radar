"""
Unit tests for ClassifierAgent, CategoryTagger, CoinTagger, SentimentAnalyzer.

All embeddings and LLM calls are mocked — no real API or DB access.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.pipeline.classifier import (
    CategoryMatch,
    CategoryTagger,
    ClassificationResult,
    ClassifierAgent,
    CoinTagger,
    SentimentAnalyzer,
    _parse_sentiment,
    classify,
    classifier_agent,
)


# ===========================================================================
# _parse_sentiment
# ===========================================================================

class TestParseSentiment:
    def test_valid_positive(self):
        assert _parse_sentiment('{"sentiment": "positive"}') == "positive"

    def test_valid_negative(self):
        assert _parse_sentiment('{"sentiment": "negative"}') == "negative"

    def test_valid_neutral(self):
        assert _parse_sentiment('{"sentiment": "neutral"}') == "neutral"

    def test_invalid_value_defaults_to_neutral(self):
        assert _parse_sentiment('{"sentiment": "bullish"}') == "neutral"

    def test_broken_json_regex_fallback(self):
        # Surrounding text makes json.loads fail; regex finds the field
        raw = 'Analysis done. {"sentiment": "positive"} confirmed.'
        assert _parse_sentiment(raw) == "positive"

    def test_completely_invalid_returns_neutral(self):
        assert _parse_sentiment("no useful content") == "neutral"

    def test_uppercase_normalised(self):
        assert _parse_sentiment('{"sentiment": "POSITIVE"}') == "positive"


# ===========================================================================
# CategoryTagger
# ===========================================================================

def _make_cat_embedding(id_, name, name_fa, vector):
    from app.core.embeddings import CategoryEmbedding
    return CategoryEmbedding(id=id_, name=name, name_fa=name_fa, vector=vector)


def _make_coin_embedding(id_, symbol, name, vector):
    from app.core.embeddings import CoinEmbedding
    return CoinEmbedding(id=id_, symbol=symbol, name=name, vector=vector)


class TestCategoryTagger:
    @pytest.mark.asyncio
    async def test_returns_matches_above_threshold(self):
        cats = [
            _make_cat_embedding(1, "DeFi", "دیفای", [1.0, 0.0]),
            _make_cat_embedding(2, "NFT",  "NFT",   [0.0, 1.0]),
        ]
        tagger = CategoryTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mock_cache, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mock_cache.embed = AsyncMock(return_value=[1.0, 0.0])   # similar to DeFi
            mock_cache.get_categories = AsyncMock(return_value=cats)
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.category_threshold": 0.72,
                "classifier.default_category": "بازار",
                "classifier.semantic_enabled": True,
                "classifier.max_classify_chars": 1500,
            }.get(k, d))

            result = await tagger.tag("DeFi liquidity pool yield farming")

        assert any(m.name == "DeFi" for m in result)
        assert all(m.score >= 0.72 for m in result)

    @pytest.mark.asyncio
    async def test_no_match_returns_default_category(self):
        # [0.0, 1.0] category is orthogonal to [1.0, 0.0] query → similarity = 0
        default_cat = _make_cat_embedding(1, "بازار", "بازار", [0.0, 1.0])
        tagger = CategoryTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mock_cache, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mock_cache.embed = AsyncMock(return_value=[1.0, 0.0])
            mock_cache.get_categories = AsyncMock(return_value=[default_cat])
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.category_threshold": 0.50,  # below similarity of 0.0
                "classifier.default_category": "بازار",
            }.get(k, d))

            result = await tagger.tag("some unrelated text")

        assert len(result) == 1
        assert result[0].name == "بازار"
        assert result[0].score == 0.0   # placeholder score for default fallback

    @pytest.mark.asyncio
    async def test_results_sorted_by_score_descending(self):
        cats = [
            _make_cat_embedding(1, "A", "A", [0.9, 0.1]),
            _make_cat_embedding(2, "B", "B", [0.8, 0.2]),
        ]
        tagger = CategoryTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mc, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mc.embed = AsyncMock(return_value=[1.0, 0.0])
            mc.get_categories = AsyncMock(return_value=cats)
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.category_threshold": 0.0,
                "classifier.default_category": "بازار",
            }.get(k, d))

            result = await tagger.tag("text")

        assert result[0].score >= result[1].score

    @pytest.mark.asyncio
    async def test_no_categories_in_db_returns_empty(self):
        tagger = CategoryTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mc, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mc.embed = AsyncMock(return_value=[1.0])
            mc.get_categories = AsyncMock(return_value=[])
            ms.get = AsyncMock(return_value=0.72)

            result = await tagger.tag("text")

        assert result == []


# ===========================================================================
# CoinTagger
# ===========================================================================

class TestCoinTagger:
    @pytest.mark.asyncio
    async def test_returns_matching_coins(self):
        coins = [
            _make_coin_embedding(1, "BTC", "Bitcoin",  [1.0, 0.0]),
            _make_coin_embedding(2, "ETH", "Ethereum", [0.0, 1.0]),
        ]
        tagger = CoinTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mc, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mc.embed = AsyncMock(return_value=[1.0, 0.0])
            mc.get_coins = AsyncMock(return_value=coins)
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.coin_threshold": 0.80,
                "classifier.keyword_match_enabled": False,
                "classifier.semantic_enabled": True,
                "classifier.max_classify_chars": 1500,
            }.get(k, d))

            result = await tagger.tag("Bitcoin price rises")

        assert "BTC" in result
        assert "ETH" not in result

    @pytest.mark.asyncio
    async def test_keyword_match_without_embedding(self):
        coins = [
            _make_coin_embedding(1, "BTC", "Bitcoin", [0.0, 1.0]),
        ]
        tagger = CoinTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mc, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mc.get_coins = AsyncMock(return_value=coins)
            mc.embed = AsyncMock()
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.keyword_match_enabled": True,
                "classifier.semantic_enabled": False,
            }.get(k, d))

            result = await tagger.tag("Bitcoin hits new high")

        assert result == ["BTC"]
        mc.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_max_5_coins_returned(self):
        coins = [
            _make_coin_embedding(i, f"C{i}", f"Coin{i}", [1.0, 0.0])
            for i in range(10)
        ]
        tagger = CoinTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mc, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mc.embed = AsyncMock(return_value=[1.0, 0.0])
            mc.get_coins = AsyncMock(return_value=coins)
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.coin_threshold": 0.0,
                "classifier.keyword_match_enabled": False,
                "classifier.semantic_enabled": True,
                "classifier.max_classify_chars": 1500,
            }.get(k, d))

            result = await tagger.tag("crypto news")

        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_no_coins_above_threshold(self):
        coins = [_make_coin_embedding(1, "BTC", "Bitcoin", [0.0, 1.0])]
        tagger = CoinTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mc, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mc.embed = AsyncMock(return_value=[1.0, 0.0])
            mc.get_coins = AsyncMock(return_value=coins)
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.coin_threshold": 0.95,
                "classifier.keyword_match_enabled": False,
                "classifier.semantic_enabled": True,
                "classifier.max_classify_chars": 1500,
            }.get(k, d))

            result = await tagger.tag("text")

        assert result == []

    @pytest.mark.asyncio
    async def test_sorted_by_score_descending(self):
        coins = [
            _make_coin_embedding(1, "A", "A", [0.9, 0.4]),   # angle ~24°
            _make_coin_embedding(2, "B", "B", [1.0, 0.0]),   # angle 0° — closer
        ]
        tagger = CoinTagger()

        with patch("app.modules.pipeline.classifier.embedding_cache") as mc, \
             patch("app.modules.pipeline.classifier.settings") as ms:
            mc.embed = AsyncMock(return_value=[1.0, 0.0])
            mc.get_coins = AsyncMock(return_value=coins)
            ms.get = AsyncMock(side_effect=lambda k, d=None: {
                "classifier.coin_threshold": 0.0,
                "classifier.keyword_match_enabled": False,
                "classifier.semantic_enabled": True,
                "classifier.max_classify_chars": 1500,
            }.get(k, d))

            result = await tagger.tag("text")

        assert result.index("B") < result.index("A")


# ===========================================================================
# SentimentAnalyzer
# ===========================================================================

class TestSentimentAnalyzer:
    @pytest.mark.asyncio
    async def test_returns_positive(self):
        from app.core.openrouter import ChatResult, ChatUsage

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=ChatResult(
            content='{"sentiment": "positive"}',
            usage=ChatUsage(0, 0, 0),
            model="gemini",
        ))

        analyzer = SentimentAnalyzer()

        with patch("app.modules.pipeline.classifier.get_agent_client", AsyncMock(return_value=mock_client)), \
             patch("app.modules.pipeline.classifier.get_agent_model", AsyncMock(return_value="google/gemini-flash-1.5")), \
             patch("app.modules.pipeline.classifier.get_agent_prompt", AsyncMock(return_value="prompt")), \
             patch("app.modules.pipeline.classifier.settings") as ms:
            ms.get = AsyncMock(return_value="google/gemini-flash-1.5")
            result = await analyzer.analyze("Bitcoin hits new ATH")

        assert result == "positive"

    @pytest.mark.asyncio
    async def test_returns_negative(self):
        from app.core.openrouter import ChatResult, ChatUsage

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=ChatResult(
            content='{"sentiment": "negative"}',
            usage=ChatUsage(0, 0, 0),
            model="gemini",
        ))

        analyzer = SentimentAnalyzer()

        with patch("app.modules.pipeline.classifier.get_agent_client", AsyncMock(return_value=mock_client)), \
             patch("app.modules.pipeline.classifier.get_agent_model", AsyncMock(return_value="google/gemini-flash-1.5")), \
             patch("app.modules.pipeline.classifier.get_agent_prompt", AsyncMock(return_value="prompt")):
            result = await analyzer.analyze("Exchange hacked, funds lost")

        assert result == "negative"

    @pytest.mark.asyncio
    async def test_api_exception_returns_neutral(self):
        analyzer = SentimentAnalyzer()

        with patch("app.modules.pipeline.classifier.get_agent_client", AsyncMock(side_effect=Exception("API down"))), \
             patch("app.modules.pipeline.classifier.get_agent_model", AsyncMock(return_value="gemini")), \
             patch("app.modules.pipeline.classifier.get_agent_prompt", AsyncMock(return_value="prompt")):
            result = await analyzer.analyze("some text")

        assert result == "neutral"

    @pytest.mark.asyncio
    async def test_invalid_json_defaults_to_neutral(self):
        from app.core.openrouter import ChatResult, ChatUsage

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=ChatResult(
            content="I cannot determine the sentiment.",
            usage=ChatUsage(0, 0, 0),
            model="gemini",
        ))

        analyzer = SentimentAnalyzer()

        with patch("app.modules.pipeline.classifier.get_agent_client", AsyncMock(return_value=mock_client)), \
             patch("app.modules.pipeline.classifier.get_agent_model", AsyncMock(return_value="gemini")), \
             patch("app.modules.pipeline.classifier.get_agent_prompt", AsyncMock(return_value="prompt")):
            result = await analyzer.analyze("text")

        assert result == "neutral"


# ===========================================================================
# ClassifierAgent
# ===========================================================================

def _make_classify_mocks(
    cat_result=None, coin_result=None, sentiment_result="neutral"
):
    """Patch all sub-components of ClassifierAgent."""
    cat_result = cat_result or [CategoryMatch(1, "بازار", "بازار", 0.85)]
    coin_result = coin_result or ["BTC"]

    agent = ClassifierAgent()
    agent.category_tagger.tag = AsyncMock(return_value=cat_result)
    agent.coin_tagger.tag = AsyncMock(return_value=coin_result)
    agent.sentiment_analyzer.analyze = AsyncMock(return_value=sentiment_result)
    return agent


class TestClassifierAgent:
    @pytest.mark.asyncio
    async def test_returns_classification_result(self):
        agent = _make_classify_mocks()
        result = await agent.classify("Bitcoin DeFi news today")

        assert isinstance(result, ClassificationResult)
        assert result.coins == ["BTC"]
        assert result.categories[0].name == "بازار"
        assert result.sentiment == "neutral"

    @pytest.mark.asyncio
    async def test_sentiment_not_called_when_no_coins(self):
        agent = ClassifierAgent()
        agent.category_tagger.tag = AsyncMock(
            return_value=[CategoryMatch(1, "بازار", "بازار", 0.8)]
        )
        agent.coin_tagger.tag = AsyncMock(return_value=[])  # no coins
        agent.sentiment_analyzer.analyze = AsyncMock(return_value="positive")

        result = await agent.classify("some news without coin mentions")

        agent.sentiment_analyzer.analyze.assert_not_called()
        assert result.sentiment is None
        assert result.coins == []

    @pytest.mark.asyncio
    async def test_sentiment_called_when_coins_found(self):
        agent = _make_classify_mocks(coin_result=["ETH"], sentiment_result="positive")
        result = await agent.classify("Ethereum upgrade news")

        agent.sentiment_analyzer.analyze.assert_called_once()
        assert result.sentiment == "positive"

    @pytest.mark.asyncio
    async def test_coin_and_category_taggers_both_called(self):
        agent = _make_classify_mocks()
        await agent.classify("crypto news")

        agent.category_tagger.tag.assert_called_once()
        agent.coin_tagger.tag.assert_called_once()

    @pytest.mark.asyncio
    async def test_multiple_categories_returned(self):
        cats = [
            CategoryMatch(1, "DeFi", "دیفای", 0.90),
            CategoryMatch(2, "بازار", "بازار", 0.80),
        ]
        agent = _make_classify_mocks(cat_result=cats)
        result = await agent.classify("DeFi market analysis")

        assert len(result.categories) == 2


# ===========================================================================
# classify() backward-compat wrapper
# ===========================================================================

class TestClassifyWrapper:
    @pytest.mark.asyncio
    async def test_returns_dict_with_expected_keys(self):
        mock_result = ClassificationResult(
            categories=[CategoryMatch(1, "DeFi", "دیفای", 0.85)],
            coins=["BTC"],
            sentiment="positive",
        )

        with patch.object(classifier_agent, "classify", AsyncMock(return_value=mock_result)):
            result = await classify("Bitcoin DeFi")

        assert "coins" in result
        assert "categories" in result
        assert "sentiment" in result
        assert result["coins"] == ["BTC"]
        assert result["categories"] == ["دیفای"]
        assert result["sentiment"] == "positive"

    @pytest.mark.asyncio
    async def test_singleton_is_classifier_agent(self):
        assert isinstance(classifier_agent, ClassifierAgent)
