"""
Unit tests for RSSPoller.

All external I/O (HTTP, Redis, DB) is mocked so tests run without
any real infrastructure.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.crawler.rss_poller import RSSPoller, RawNewsItem, _FeedEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _source(
    id: int = 1,
    name: str = "TestFeed",
    rss_url: str = "https://example.com/feed.xml",
    language: str = "en",
    priority: int = 5,
    is_active: bool = True,
):
    src = MagicMock()
    src.id = id
    src.name = name
    src.rss_url = rss_url
    src.language = language
    src.priority = priority
    src.is_active = is_active
    return src


def _entry(
    url: str = "https://example.com/news/1",
    title: str = "Bitcoin Hits 100k",
    summary: str | None = "BTC reaches new ATH",
    published_at: datetime | None = None,
) -> _FeedEntry:
    return _FeedEntry(
        url=url,
        title=title,
        summary=summary,
        published_at=published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        raw=MagicMock(),
    )


@pytest.fixture
def poller() -> RSSPoller:
    return RSSPoller()


# ---------------------------------------------------------------------------
# _make_entry — parses feedparser AttrDict into _FeedEntry
# ---------------------------------------------------------------------------

def _feedparser_entry(link="https://a.com/1", title="BTC News", summary="desc"):
    e = MagicMock()
    e.link = link
    e.title = title
    e.summary = summary
    e.published_parsed = time.strptime("2026-01-15", "%Y-%m-%d")
    e.updated_parsed = None
    return e


def test_make_entry_parses_fields():
    raw = _feedparser_entry()
    entry = RSSPoller._make_entry(raw)
    assert entry.url == "https://a.com/1"
    assert entry.title == "BTC News"
    assert entry.summary == "desc"
    assert entry.published_at is not None
    assert entry.published_at.tzinfo == timezone.utc


def test_make_entry_falls_back_to_updated_parsed():
    raw = MagicMock()
    raw.link = "https://a.com/2"
    raw.title = "ETH Update"
    raw.summary = ""
    raw.published_parsed = None
    raw.updated_parsed = time.strptime("2026-02-01", "%Y-%m-%d")
    entry = RSSPoller._make_entry(raw)
    assert entry.published_at is not None


def test_make_entry_handles_missing_published():
    raw = MagicMock()
    raw.link = "https://a.com/3"
    raw.title = "No Date"
    raw.summary = None
    raw.published_parsed = None
    raw.updated_parsed = None
    entry = RSSPoller._make_entry(raw)
    assert entry.published_at is None


def test_make_entry_strips_whitespace():
    raw = _feedparser_entry(link="  https://a.com/4  ", title="  Spaced Title  ")
    entry = RSSPoller._make_entry(raw)
    assert entry.url == "https://a.com/4"
    assert entry.title == "Spaced Title"


def test_make_entry_empty_summary_becomes_none():
    raw = _feedparser_entry(summary="")
    entry = RSSPoller._make_entry(raw)
    assert entry.summary is None


# ---------------------------------------------------------------------------
# poll_source — core logic (mocked _parse_feed and dedup)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_source_returns_new_items(poller):
    entries = [_entry(url="https://a.com/1", title="BTC News")]

    poller._parse_feed = AsyncMock(return_value=entries)

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", return_value=False) as mock_dedup:

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(_source(language="en"))

    assert len(items) == 1
    assert items[0].url == "https://a.com/1"
    assert items[0].title == "BTC News"
    assert items[0].content == ""   # not yet fetched


@pytest.mark.asyncio
async def test_poll_source_dedup_skips_seen_url(poller):
    entries = [_entry(url="https://a.com/1")]

    poller._parse_feed = AsyncMock(return_value=entries)

    # First call (url hash): duplicate = True → skip immediately
    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", return_value=True):

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(_source())

    assert items == []


@pytest.mark.asyncio
async def test_poll_source_dedup_skips_seen_title(poller):
    entries = [_entry(url="https://a.com/new-url", title="Bitcoin Hits 100k")]

    poller._parse_feed = AsyncMock(return_value=entries)

    # URL hash → new; title hash → duplicate
    call_count = 0

    async def side_effect(hash_val, window):
        nonlocal call_count
        call_count += 1
        return call_count > 1   # second call (title) returns True

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", side_effect=side_effect):

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(_source())

    assert items == []
    assert call_count == 2


@pytest.mark.asyncio
async def test_poll_source_whitelist_skips_fa_irrelevant(poller):
    entries = [_entry(title="Today's weather forecast")]  # no crypto keywords

    poller._parse_feed = AsyncMock(return_value=entries)

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", return_value=False):

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(_source(language="fa"))

    assert items == []


@pytest.mark.asyncio
async def test_poll_source_whitelist_not_applied_for_en(poller):
    entries = [_entry(title="Today's weather forecast")]

    poller._parse_feed = AsyncMock(return_value=entries)

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", return_value=False):

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(_source(language="en"))

    # EN sources skip whitelist — any item is allowed through
    assert len(items) == 1


@pytest.mark.asyncio
async def test_poll_source_whitelist_passes_fa_crypto(poller):
    entries = [_entry(title="بیت‌کوین امروز ۱۰۰ هزار دلار شد")]

    poller._parse_feed = AsyncMock(return_value=entries)

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", return_value=False):

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(_source(language="fa"))

    assert len(items) == 1


@pytest.mark.asyncio
async def test_poll_source_skips_entry_without_url(poller):
    entries = [_entry(url="", title="No URL")]

    poller._parse_feed = AsyncMock(return_value=entries)

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", return_value=False):

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(_source())

    assert items == []


@pytest.mark.asyncio
async def test_poll_source_sets_raw_news_item_fields(poller):
    pub = datetime(2026, 3, 1, tzinfo=timezone.utc)
    entries = [_entry(
        url="https://a.com/story",
        title="ETH Upgrade",
        summary="Ethereum completes merge",
        published_at=pub,
    )]
    src = _source(id=7, name="CoinDesk", language="en")

    poller._parse_feed = AsyncMock(return_value=entries)

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings, \
         patch("app.modules.crawler.rss_poller.is_duplicate", return_value=False):

        mock_settings.get = AsyncMock(return_value=24)
        items = await poller.poll_source(src)

    item = items[0]
    assert item.url == "https://a.com/story"
    assert item.title == "ETH Upgrade"
    assert item.source_id == 7
    assert item.source_name == "CoinDesk"
    assert item.language == "en"
    assert item.published_at == pub
    assert item.feed_summary == "Ethereum completes merge"
    assert item.content == ""
    assert len(item.title_hash) == 64   # SHA-256 hex digest


# ---------------------------------------------------------------------------
# poll_all_sources — concurrency + aggregation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_all_sources_aggregates_items(poller):
    src_a = _source(id=1, name="A")
    src_b = _source(id=2, name="B")

    poller._load_due_sources = AsyncMock(return_value=[src_a, src_b])
    poller._record_poll_result = AsyncMock()

    items_a = [_entry(url="https://a.com/1", title="BTC")]
    items_b = [_entry(url="https://b.com/1", title="ETH"), _entry(url="https://b.com/2", title="SOL")]

    async def _poll_source(source):
        return items_a if source.name == "A" else items_b

    poller.poll_source = _poll_source

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=5)
        result = await poller.poll_all_sources()

    assert len(result) == 3


@pytest.mark.asyncio
async def test_poll_all_sources_handles_source_exception(poller):
    src_ok = _source(id=1, name="Good")
    src_err = _source(id=2, name="Bad")

    poller._load_due_sources = AsyncMock(return_value=[src_ok, src_err])
    poller._record_poll_result = AsyncMock()

    good_item = _entry(url="https://ok.com/1", title="BTC")

    async def _poll_source(source):
        if source.name == "Bad":
            raise ConnectionError("timeout")
        return [good_item]

    poller.poll_source = _poll_source

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=5)
        result = await poller.poll_all_sources()

    # Only the good source's item should appear; error is swallowed
    assert len(result) == 1


@pytest.mark.asyncio
async def test_poll_all_sources_empty_when_no_sources(poller):
    poller._load_due_sources = AsyncMock(return_value=[])

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=5)
        result = await poller.poll_all_sources()

    assert result == []


@pytest.mark.asyncio
async def test_poll_all_sources_respects_semaphore(poller):
    """Verify that at most max_concurrent tasks run in parallel."""
    concurrency_tracker = {"current": 0, "peak": 0}

    sources = [_source(id=i, name=f"S{i}") for i in range(10)]
    poller._load_due_sources = AsyncMock(return_value=sources)
    poller._record_poll_result = AsyncMock()

    async def _poll_source(source):
        concurrency_tracker["current"] += 1
        concurrency_tracker["peak"] = max(
            concurrency_tracker["peak"], concurrency_tracker["current"]
        )
        await asyncio.sleep(0.01)
        concurrency_tracker["current"] -= 1
        return []

    poller.poll_source = _poll_source

    with patch("app.modules.crawler.rss_poller.settings") as mock_settings:
        mock_settings.get = AsyncMock(return_value=3)   # max 3 concurrent
        await poller.poll_all_sources()

    assert concurrency_tracker["peak"] <= 3
