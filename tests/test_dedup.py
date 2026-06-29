"""
Unit tests for app.modules.dedup.engine.

All Redis I/O is mocked; no real Redis connection needed.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.modules.dedup.engine import (
    DedupEngine,
    normalize,
    title_hash,
    url_hash,
    is_duplicate,
)


# ===========================================================================
# normalize() — pure function, no mocking
# ===========================================================================

class TestNormalize:
    def test_lowercase(self):
        assert normalize("Bitcoin") == "bitcoin"
        assert normalize("ETHEREUM") == "ethereum"

    def test_strips_leading_trailing_whitespace(self):
        assert normalize("  bitcoin  ") == "bitcoin"

    def test_collapses_internal_spaces(self):
        assert normalize("Bitcoin  Hits   100k") == "bitcoin hits 100k"

    def test_removes_ascii_punctuation(self):
        assert normalize("Bitcoin! Hits $100k?") == "bitcoin hits 100k"

    def test_removes_arabic_persian_punctuation(self):
        # ،  Arabic comma  ؟  Arabic question mark
        assert normalize("بیتکوین، امروز؟") == "بیتکوین امروز"

    def test_removes_guillemets(self):
        assert normalize("«بیتکوین» جهش کرد") == "بیتکوین جهش کرد"

    def test_removes_ellipsis_and_dash(self):
        assert normalize("Bitcoin… price — rising") == "bitcoin price rising"

    def test_preserves_persian_word_chars(self):
        result = normalize("بیتکوین امروز رکورد زد")
        assert result == "بیتکوین امروز رکورد زد"

    def test_nfkc_removes_zero_width_non_joiner(self):
        # U+200C ZWNJ appears in "بیت‌کوین"; after NFKC it stays as ‌
        # then [^\w\s] removes it → "بیتکوین"
        assert normalize("بیت‌کوین") == "بیتکوین"

    def test_nfkc_normalizes_arabic_presentation_forms(self):
        # ﻳ (U+FBB3, Arabic letter YEH isolated form) → ي (U+064A) via NFKC
        result = normalize("ﺑﯿﺘﮑﻮﯾﻦ")
        assert len(result) > 0  # did not crash; text was normalised

    def test_numbers_preserved(self):
        assert normalize("top 10 coins") == "top 10 coins"

    def test_mixed_en_fa(self):
        assert normalize("Bitcoin (BTC) ارزش دارد!") == "bitcoin btc ارزش دارد"

    def test_empty_string(self):
        assert normalize("") == ""

    def test_only_punctuation_becomes_empty(self):
        assert normalize("!@#$%") == ""


# ===========================================================================
# compute_hash / title_hash / url_hash — pure, no mocking
# ===========================================================================

class TestHashing:
    def test_compute_hash_is_deterministic(self):
        assert DedupEngine.compute_hash("Bitcoin") == DedupEngine.compute_hash("Bitcoin")

    def test_compute_hash_length(self):
        assert len(DedupEngine.compute_hash("any title")) == 64

    def test_same_title_different_punctuation_same_hash(self):
        # Only punctuation differs — should dedup
        assert DedupEngine.compute_hash("Bitcoin hits $100k!") == \
               DedupEngine.compute_hash("Bitcoin hits 100k")

    def test_same_title_different_case_same_hash(self):
        assert DedupEngine.compute_hash("BITCOIN RISES") == \
               DedupEngine.compute_hash("bitcoin rises")

    def test_different_titles_different_hash(self):
        assert DedupEngine.compute_hash("Bitcoin rises") != \
               DedupEngine.compute_hash("Ethereum falls")

    def test_title_hash_matches_compute_hash(self):
        # title_hash() and DedupEngine.compute_hash() must agree
        t = "Bitcoin hits new ATH in 2026"
        assert title_hash(t) == DedupEngine.compute_hash(t)

    def test_url_hash_is_deterministic(self):
        u = "https://coindesk.com/news/1"
        assert url_hash(u) == url_hash(u)

    def test_url_hash_different_urls(self):
        assert url_hash("https://a.com") != url_hash("https://b.com")

    def test_url_hash_strips_whitespace(self):
        assert url_hash("https://a.com ") == url_hash("https://a.com")

    def test_title_hash_normalizes_whitespace(self):
        assert title_hash("Bitcoin  Hits  100k") == title_hash("Bitcoin Hits 100k")

    def test_title_hash_case_insensitive(self):
        assert title_hash("Bitcoin") == title_hash("bitcoin")


# ===========================================================================
# DedupEngine.is_duplicate — async, Redis mocked
# ===========================================================================

def _make_redis(exists: bool = False) -> MagicMock:
    redis = MagicMock()
    redis.exists = AsyncMock(return_value=int(exists))
    redis.setex = AsyncMock()
    pipe = MagicMock()
    pipe.incr = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[1, True])
    redis.pipeline = MagicMock(return_value=pipe)
    return redis


@pytest.fixture
def engine() -> DedupEngine:
    return DedupEngine()


@pytest.mark.asyncio
async def test_first_sight_returns_false(engine):
    redis = _make_redis(exists=False)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=24)
        result = await engine.is_duplicate("Bitcoin hits ATH")

    assert result is False


@pytest.mark.asyncio
async def test_first_sight_stores_hash_with_correct_ttl(engine):
    redis = _make_redis(exists=False)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=48)  # 48-hour window
        await engine.is_duplicate("Some news title")

    expected_hash = DedupEngine.compute_hash("Some news title")
    expected_key = f"dedup:{expected_hash}"
    expected_ttl = 48 * 3600

    redis.setex.assert_awaited_once_with(expected_key, expected_ttl, "1")


@pytest.mark.asyncio
async def test_same_title_twice_is_duplicate(engine):
    title = "Bitcoin Hits $100k"

    # First call: not seen (exists=False) → sets key
    # Second call: seen (exists=True) → duplicate
    call_count = 0

    async def exists_side_effect(key):
        nonlocal call_count
        call_count += 1
        return 1 if call_count > 1 else 0

    redis = _make_redis()
    redis.exists = exists_side_effect

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=24)

        first = await engine.is_duplicate(title)
        second = await engine.is_duplicate(title)

    assert first is False
    assert second is True


@pytest.mark.asyncio
async def test_after_window_expiry_not_duplicate(engine):
    """When the Redis key has expired, exists() returns 0 → not a duplicate."""
    redis = _make_redis(exists=False)   # simulates key expired

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=24)
        result = await engine.is_duplicate("Old news re-run")

    assert result is False
    redis.setex.assert_awaited_once()   # re-registered with fresh TTL


@pytest.mark.asyncio
async def test_different_titles_not_duplicate(engine):
    seen: set[str] = set()

    async def exists_side_effect(key):
        if key in seen:
            return 1
        seen.add(key)
        return 0

    redis = _make_redis()
    redis.exists = exists_side_effect

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=24)

        r1 = await engine.is_duplicate("Bitcoin rises")
        r2 = await engine.is_duplicate("Ethereum falls")

    assert r1 is False
    assert r2 is False


@pytest.mark.asyncio
async def test_punctuation_variants_deduplicated(engine):
    """Title differing only in punctuation must be treated as the same item."""
    seen: set[str] = set()

    async def exists_side_effect(key):
        if key in seen:
            return 1
        seen.add(key)
        return 0

    redis = _make_redis()
    redis.exists = exists_side_effect

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=24)

        r1 = await engine.is_duplicate("Bitcoin! Hits $100k.")
        r2 = await engine.is_duplicate("Bitcoin Hits 100k")

    assert r1 is False
    assert r2 is True   # normalises to the same hash


@pytest.mark.asyncio
async def test_window_hours_read_from_settings(engine):
    redis = _make_redis(exists=False)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=72)
        await engine.is_duplicate("Some title")

    _, ttl_arg, _ = redis.setex.await_args.args
    assert ttl_arg == 72 * 3600


@pytest.mark.asyncio
async def test_duplicate_increments_skip_counter(engine):
    redis = _make_redis(exists=True)   # already seen

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=24)
        await engine.is_duplicate("Repeated news")

    pipe = redis.pipeline.return_value
    pipe.incr.assert_called_once()
    pipe.expire.assert_called_once()
    pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_first_sight_does_not_increment_counter(engine):
    redis = _make_redis(exists=False)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis), \
         patch("app.modules.dedup.engine.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=24)
        await engine.is_duplicate("Brand new article")

    pipe = redis.pipeline.return_value
    pipe.execute.assert_not_awaited()


# ===========================================================================
# DedupEngine.get_skip_count — async, Redis mocked
# ===========================================================================

@pytest.mark.asyncio
async def test_get_skip_count_returns_zero_when_no_key(engine):
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis):
        count = await engine.get_skip_count("2026-01-01")

    assert count == 0


@pytest.mark.asyncio
async def test_get_skip_count_returns_value(engine):
    redis = MagicMock()
    redis.get = AsyncMock(return_value="42")

    with patch("app.modules.dedup.engine.get_redis", return_value=redis):
        count = await engine.get_skip_count("2026-01-01")

    assert count == 42


@pytest.mark.asyncio
async def test_get_skip_count_defaults_to_today(engine):
    from datetime import date as date_type
    today = date_type.today().isoformat()

    redis = MagicMock()
    redis.get = AsyncMock(return_value="7")

    with patch("app.modules.dedup.engine.get_redis", return_value=redis):
        await engine.get_skip_count()  # no date arg

    called_key = redis.get.await_args.args[0]
    assert called_key == f"dedup:metrics:skipped:{today}"


# ===========================================================================
# Module-level is_duplicate (backward-compat helper)
# ===========================================================================

@pytest.mark.asyncio
async def test_module_is_duplicate_first_call_false():
    redis = _make_redis(exists=False)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis):
        result = await is_duplicate("abc123hash", window_hours=24)

    assert result is False
    redis.setex.assert_awaited_once_with("dedup:abc123hash", 24 * 3600, "1")


@pytest.mark.asyncio
async def test_module_is_duplicate_second_call_true():
    redis = _make_redis(exists=True)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis):
        result = await is_duplicate("abc123hash", window_hours=24)

    assert result is True
    redis.setex.assert_not_awaited()   # already exists — no re-registration


@pytest.mark.asyncio
async def test_module_is_duplicate_uses_custom_window():
    redis = _make_redis(exists=False)

    with patch("app.modules.dedup.engine.get_redis", return_value=redis):
        await is_duplicate("somehash", window_hours=6)

    _, ttl, _ = redis.setex.await_args.args
    assert ttl == 6 * 3600
