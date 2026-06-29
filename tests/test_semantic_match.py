"""Tests for semantic keyword matching helpers."""
from __future__ import annotations

from app.modules.pipeline.semantic_match import match_coins_by_keywords, resolve_default_category


class TestMatchCoinsByKeywords:
    def test_matches_symbol_and_name(self):
        coins = [("BTC", "Bitcoin", '["بیت کوین"]'), ("ETH", "Ethereum", None)]
        text = "قیمت Bitcoin (BTC) امروز بالا رفت"
        assert match_coins_by_keywords(text, coins) == ["BTC"]

    def test_matches_persian_alias(self):
        coins = [("BTC", "Bitcoin", '["بیت کوین"]')]
        assert match_coins_by_keywords("قیمت بیت کوین", coins) == ["BTC"]

    def test_max_five(self):
        coins = [(f"C{i}", f"Coin{i}", None) for i in range(10)]
        text = " ".join(f"Coin{i}" for i in range(10))
        assert len(match_coins_by_keywords(text, coins)) == 5


class TestResolveDefaultCategory:
    def test_exact_match(self):
        cats = [(1, "market-news", "اخبار بازار"), (2, "bitcoin", "بیت‌کوین")]
        r = resolve_default_category(cats, "اخبار بازار")
        assert r == (1, "market-news", "اخبار بازار")

    def test_partial_market_fallback(self):
        cats = [(1, "market-news", "اخبار بازار")]
        r = resolve_default_category(cats, "بازار")
        assert r == (1, "market-news", "اخبار بازار")

    def test_no_match(self):
        assert resolve_default_category([], "بازار") is None
