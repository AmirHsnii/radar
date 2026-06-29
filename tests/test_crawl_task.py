"""
Unit tests for app.tasks.crawl_task.

All DB, Redis, and Celery I/O is mocked.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.modules.crawler.rss_poller import RawNewsItem
from app.modules.dedup.engine import url_hash as compute_url_hash
from app.tasks.crawl_task import _persist, _poll, _retry_dlq


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_item(
    url: str = "https://example.com/news/1",
    title: str = "Bitcoin ATH",
    language: str = "en",
    source_id: int = 1,
    source_name: str = "TestFeed",
    published_at: datetime | None = None,
) -> RawNewsItem:
    from app.modules.dedup.engine import title_hash
    return RawNewsItem(
        url=url,
        title=title,
        title_hash=title_hash(title),
        content="",
        language=language,
        source_id=source_id,
        source_name=source_name,
        published_at=published_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        feed_summary=None,
    )


def _make_session(exists_id=None):
    """Return a mock AsyncSession that behaves like an async context manager."""
    session = MagicMock()
    session.scalar = AsyncMock(return_value=exists_id)
    session.scalars = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, session


# ===========================================================================
# _persist
# ===========================================================================

@pytest.mark.asyncio
async def test_persist_inserts_new_item():
    item = _raw_item(url="https://example.com/1", title="BTC News")

    cm, session = _make_session(exists_id=None)  # not in DB

    # Simulate flush populating row.id
    added_rows = []

    def capture_add(row):
        row.id = 42
        added_rows.append(row)

    session.add = capture_add

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm):
        result = await _persist([item])

    assert item.url in result
    assert result[item.url] == 42


@pytest.mark.asyncio
async def test_persist_skips_existing_item():
    item = _raw_item(url="https://example.com/1")

    cm, session = _make_session(exists_id=99)  # already in DB

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm):
        result = await _persist([item])

    assert result == {}
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_persist_dedup_check_uses_url_hash():
    item = _raw_item(url="https://example.com/article/123")

    cm, session = _make_session(exists_id=None)

    captured_args = []

    async def capture_scalar(stmt):
        captured_args.append(stmt)
        return None

    session.scalar = capture_scalar

    added = []

    def capture_add(row):
        row.id = 1
        added.append(row)

    session.add = capture_add

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm):
        await _persist([item])

    # url_hash column should be SHA-256 of the URL, not the title hash
    inserted_row = added[0]
    assert inserted_row.url_hash == compute_url_hash(item.url)
    assert inserted_row.title_hash == item.title_hash
    assert inserted_row.url_hash != item.title_hash  # they must differ


@pytest.mark.asyncio
async def test_persist_sets_published_at():
    pub = datetime(2026, 3, 15, tzinfo=timezone.utc)
    item = _raw_item(published_at=pub)

    cm, session = _make_session(exists_id=None)
    added = []

    def capture_add(row):
        row.id = 5
        added.append(row)

    session.add = capture_add

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm):
        await _persist([item])

    assert added[0].published_at == pub


@pytest.mark.asyncio
async def test_persist_handles_multiple_items():
    items = [
        _raw_item(url="https://a.com/1", title="BTC"),
        _raw_item(url="https://a.com/2", title="ETH"),
        _raw_item(url="https://a.com/3", title="SOL"),
    ]

    call_count = 0
    added = []

    async def fake_scalar(stmt):
        return None  # none exist in DB

    async def fake_flush():
        pass

    def fake_add(row):
        nonlocal call_count
        call_count += 1
        row.id = call_count
        added.append(row)

    cm, session = _make_session()
    session.scalar = fake_scalar
    session.flush = fake_flush
    session.add = fake_add

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm):
        result = await _persist(items)

    assert len(result) == 3
    assert set(result.values()) == {1, 2, 3}


@pytest.mark.asyncio
async def test_persist_partial_duplicates():
    """Two items: one new, one already in DB."""
    items = [
        _raw_item(url="https://a.com/new", title="New Article"),
        _raw_item(url="https://a.com/old", title="Old Article"),
    ]
    new_url_hash = compute_url_hash("https://a.com/new")
    old_url_hash = compute_url_hash("https://a.com/old")

    added = []

    async def fake_scalar(stmt):
        # Simulate: new_url → None (not in DB), old_url → 77 (in DB)
        # We intercept based on call order
        return None if not added else 77

    def fake_add(row):
        row.id = 10
        added.append(row)

    cm, session = _make_session()
    session.scalar = fake_scalar
    session.add = fake_add

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm):
        result = await _persist(items)

    assert len(result) == 1
    assert "https://a.com/new" in result


# ===========================================================================
# _poll
# ===========================================================================

def _mock_process_module():
    """
    Return a sys.modules-compatible mock for app.tasks.process_task.

    process_task imports langdetect (via orchestrator → router) which is not
    installed in the test environment.  We inject a module-level mock so that
    the lazy `from app.tasks.process_task import process_news_item_task` inside
    _poll() and _retry_dlq() resolves without hitting the real module.
    """
    import sys
    mock_mod = MagicMock()
    mock_mod.process_news_item_task = MagicMock()
    return mock_mod


@pytest.mark.asyncio
async def test_poll_dispatches_process_task_for_each_saved():
    import sys
    items = [_raw_item(url="https://a.com/1"), _raw_item(url="https://a.com/2")]

    mock_mod = _mock_process_module()

    with patch("app.tasks.crawl_task.poll_all_sources", AsyncMock(return_value=items)), \
         patch("app.tasks.crawl_task._persist", AsyncMock(return_value={
             "https://a.com/1": 10,
             "https://a.com/2": 11,
         })), \
         patch.dict(sys.modules, {"app.tasks.process_task": mock_mod}):
        result = await _poll()

    assert mock_mod.process_news_item_task.delay.call_count == 2
    mock_mod.process_news_item_task.delay.assert_any_call(10)
    mock_mod.process_news_item_task.delay.assert_any_call(11)


@pytest.mark.asyncio
async def test_poll_returns_empty_when_no_items():
    with patch("app.tasks.crawl_task.poll_all_sources", AsyncMock(return_value=[])):
        result = await _poll()

    assert result == {}


@pytest.mark.asyncio
async def test_poll_no_dispatch_when_all_duplicates():
    import sys
    items = [_raw_item(url="https://a.com/1")]

    mock_mod = _mock_process_module()

    with patch("app.tasks.crawl_task.poll_all_sources", AsyncMock(return_value=items)), \
         patch("app.tasks.crawl_task._persist", AsyncMock(return_value={})), \
         patch.dict(sys.modules, {"app.tasks.process_task": mock_mod}):
        result = await _poll()

    mock_mod.process_news_item_task.delay.assert_not_called()
    assert result == {}


# ===========================================================================
# _retry_dlq
# ===========================================================================

def _dlq_item(news_id: int = 1, status: str = "pending") -> MagicMock:
    item = MagicMock()
    item.news_id = news_id
    item.status = status
    return item


@pytest.mark.asyncio
async def test_retry_dlq_dispatches_due_items():
    import sys
    dlq_items = [_dlq_item(news_id=5), _dlq_item(news_id=6)]

    mock_mod = _mock_process_module()
    cm, session = _make_session()
    session.scalars = AsyncMock(return_value=iter(dlq_items))

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm), \
         patch.dict(sys.modules, {"app.tasks.process_task": mock_mod}):
        count = await _retry_dlq()

    assert count == 2
    mock_mod.process_news_item_task.delay.assert_any_call(5)
    mock_mod.process_news_item_task.delay.assert_any_call(6)


@pytest.mark.asyncio
async def test_retry_dlq_marks_status_retrying():
    import sys
    dlq_items = [_dlq_item(news_id=3)]

    mock_mod = _mock_process_module()
    cm, session = _make_session()
    session.scalars = AsyncMock(return_value=iter(dlq_items))

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm), \
         patch.dict(sys.modules, {"app.tasks.process_task": mock_mod}):
        await _retry_dlq()

    assert dlq_items[0].status == "retrying"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_dlq_returns_zero_when_nothing_due():
    import sys
    mock_mod = _mock_process_module()
    cm, session = _make_session()
    session.scalars = AsyncMock(return_value=iter([]))

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm), \
         patch.dict(sys.modules, {"app.tasks.process_task": mock_mod}):
        count = await _retry_dlq()

    assert count == 0


@pytest.mark.asyncio
async def test_retry_dlq_skips_items_without_news_id():
    import sys
    item_with = _dlq_item(news_id=10)
    item_without = _dlq_item(news_id=None)

    mock_mod = _mock_process_module()
    cm, session = _make_session()
    session.scalars = AsyncMock(return_value=iter([item_with, item_without]))

    with patch("app.tasks.crawl_task.AsyncSessionLocal", return_value=cm), \
         patch.dict(sys.modules, {"app.tasks.process_task": mock_mod}):
        count = await _retry_dlq()

    assert count == 1
    mock_mod.process_news_item_task.delay.assert_called_once_with(10)


# ===========================================================================
# celery_beat — schedule configuration
# ===========================================================================

def test_beat_schedule_has_required_tasks():
    """Static fallback schedule must define both tasks."""
    from celery_beat import celery_app as beat_app
    schedule = beat_app.conf.beat_schedule
    assert "poll-rss-sources" in schedule
    assert "retry-dlq-items" in schedule


def test_beat_schedule_poll_uses_timedelta():
    from datetime import timedelta
    from celery_beat import celery_app as beat_app
    poll_schedule = beat_app.conf.beat_schedule["poll-rss-sources"]["schedule"]
    assert isinstance(poll_schedule, timedelta)


def test_beat_build_schedule_respects_interval():
    from datetime import timedelta
    from celery_beat import _build_schedule
    schedule = _build_schedule(45)
    assert schedule["poll-rss-sources"]["schedule"] == timedelta(minutes=45)


def test_beat_dlq_interval_is_30_min():
    from datetime import timedelta
    from celery_beat import _build_schedule
    schedule = _build_schedule(15)
    assert schedule["retry-dlq-items"]["schedule"] == timedelta(minutes=30)


@pytest.mark.asyncio
async def test_beat_reads_interval_from_settings():
    from celery_beat import _read_poll_interval

    mock_settings = MagicMock()
    mock_settings.get = AsyncMock(return_value=20)

    with patch("celery_beat.signals"):  # don't fire signal during import
        with patch("app.config.settings", mock_settings):
            # We patch inside _read_poll_interval's import
            import celery_beat
            with patch.object(
                celery_beat,
                "_read_poll_interval",
                AsyncMock(return_value=20),
            ):
                interval = await celery_beat._read_poll_interval()

    assert interval == 20


def test_on_beat_init_updates_schedule():
    """beat_init signal handler should update the app schedule."""
    from celery_beat import on_beat_init, _DEFAULT_POLL_INTERVAL

    mock_app = MagicMock()
    mock_app.conf.beat_schedule = {}
    mock_sender = MagicMock()
    mock_sender.app = mock_app

    with patch("celery_beat._read_poll_interval", AsyncMock(return_value=25)):
        on_beat_init(mock_sender)

    from datetime import timedelta
    assert mock_app.conf.beat_schedule["poll-rss-sources"]["schedule"] == timedelta(minutes=25)


def test_on_beat_init_falls_back_on_db_error():
    """If DB is unreachable, beat_init should use the default interval."""
    from celery_beat import on_beat_init, _DEFAULT_POLL_INTERVAL

    mock_app = MagicMock()
    mock_app.conf.beat_schedule = {}
    mock_sender = MagicMock()
    mock_sender.app = mock_app

    with patch("celery_beat._read_poll_interval", AsyncMock(side_effect=OSError("DB down"))):
        on_beat_init(mock_sender)

    from datetime import timedelta
    expected = timedelta(minutes=_DEFAULT_POLL_INTERVAL)
    assert mock_app.conf.beat_schedule["poll-rss-sources"]["schedule"] == expected
