"""
RSSPoller — discovers new articles from active RSS sources.

Flow per source:
  httpx fetch → feedparser parse → whitelist filter (FA only)
  → URL-hash dedup → title-hash dedup → RawNewsItem

poll_all_sources() uses asyncio.Semaphore to bound concurrency.
Nothing is written to DB here; persistence is the Celery task's job.
"""
from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
import structlog

from sqlalchemy import select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.source import Source
from app.modules.crawler.whitelist import passes_whitelist
from app.modules.dedup.engine import is_duplicate, title_hash, url_hash

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Public data model  (matches MODULE_01_CRAWLER.md spec)
# ---------------------------------------------------------------------------

@dataclass
class RawNewsItem:
    url: str
    title: str
    title_hash: str          # SHA-256(normalize(title))
    content: str             # always "" here; filled later by ContentFetcher
    language: str            # "fa" | "en"
    source_id: int
    source_name: str
    published_at: datetime | None
    feed_summary: str | None  # RSS-provided excerpt, if present


# ---------------------------------------------------------------------------
# Internal feed entry (intermediate representation after feedparser)
# ---------------------------------------------------------------------------

@dataclass
class _FeedEntry:
    url: str
    title: str
    summary: str | None
    published_at: datetime | None
    raw: Any = field(repr=False)


# ---------------------------------------------------------------------------
# RSSPoller
# ---------------------------------------------------------------------------

class RSSPoller:
    """
    Stateless poller.  Create once per Celery beat tick.

    Concurrency is bounded by the ``crawler.max_concurrent_fetches`` setting
    (default 5).  Sources are sorted by ``priority`` descending so the most
    important feeds are polled first when the semaphore is the bottleneck.
    """

    # -- public API ----------------------------------------------------------

    async def poll_all_sources(self) -> list[RawNewsItem]:
        """
        Poll active sources whose per-source interval has elapsed.
        Sources without poll_interval_minutes use the global default.
        """
        sources = await self._load_due_sources()
        if not sources:
            log.info("rss_poll.no_due_sources")
            return []

        max_concurrent = int(await settings.get("crawler.max_concurrent_fetches", 5))
        sem = asyncio.Semaphore(max_concurrent)

        log.info(
            "rss_poll.started",
            due_sources=len(sources),
            max_concurrent=max_concurrent,
        )

        async def _bounded(source: Source) -> list[RawNewsItem]:
            async with sem:
                try:
                    items = await self.poll_source(source)
                    if items:
                        await self._record_poll_result(
                            source.id,
                            status="success",
                            new_items=len(items),
                            message=f"{len(items)} خبر جدید",
                        )
                    else:
                        await self._record_poll_result(
                            source.id,
                            status="empty",
                            new_items=0,
                            message="بدون خبر جدید",
                        )
                    return items
                except BaseException as exc:
                    await self._record_poll_result(
                        source.id,
                        status="error",
                        new_items=0,
                        message=str(exc)[:500],
                    )
                    raise

        results = await asyncio.gather(
            *[_bounded(s) for s in sources],
            return_exceptions=True,
        )

        items: list[RawNewsItem] = []
        for source, result in zip(sources, results):
            if isinstance(result, BaseException):
                log.error(
                    "rss_poll.source_error",
                    source=source.name,
                    error=str(result),
                )
            else:
                if result:
                    log.info(
                        "rss_poll.source_done",
                        source=source.name,
                        new_items=len(result),
                    )
                items.extend(result)

        log.info("rss_poll.finished", total_new=len(items))
        return items

    async def poll_source(self, source: Source) -> list[RawNewsItem]:
        """
        Parse one source's RSS feed and return new items that pass all filters.
        """
        slog = log.bind(source=source.name, language=source.language)
        slog.debug("rss_poll.fetching_feed", url=source.rss_url)

        entries = await self._parse_feed(source.rss_url)
        if not entries:
            slog.debug("rss_poll.feed_empty")
            return []

        window_hours = int(await settings.get("dedup.window_hours", 24))
        items: list[RawNewsItem] = []

        for entry in entries:
            if not entry.url or not entry.title:
                continue

            # Whitelist — only applied to Persian sources.
            # English sources assume all content is crypto-relevant by source.
            if not passes_whitelist(entry.title, source.language):
                slog.debug(
                    "rss_poll.whitelist_skip",
                    title=entry.title[:80],
                )
                continue

            # Dedup by URL hash
            u_hash = url_hash(entry.url)
            if await is_duplicate(u_hash, window_hours):
                continue

            # Dedup by normalised title hash — catches the same story republished
            # under a different URL (common on aggregators).
            t_hash = title_hash(entry.title)
            if await is_duplicate(t_hash, window_hours):
                slog.debug(
                    "rss_poll.title_dedup_skip",
                    title=entry.title[:80],
                )
                continue

            items.append(
                RawNewsItem(
                    url=entry.url,
                    title=entry.title,
                    title_hash=t_hash,
                    content="",
                    language=source.language,
                    source_id=source.id,
                    source_name=source.name,
                    published_at=entry.published_at,
                    feed_summary=entry.summary,
                )
            )

        slog.info(
            "rss_poll.source_scanned",
            feed_entries=len(entries),
            new_items=len(items),
        )
        return items

    async def preview_feed(
        self,
        source: Source,
        limit: int = 5,
    ) -> list[dict]:
        """
        Return the latest feed entries without dedup — for admin test/preview.
        """
        entries = await self._parse_feed(source.rss_url)
        preview: list[dict] = []

        for entry in entries[:limit]:
            if not entry.url or not entry.title:
                continue
            wl_ok = passes_whitelist(entry.title, source.language)
            preview.append({
                "url": entry.url,
                "title": entry.title,
                "summary": (entry.summary or "")[:300] or None,
                "published_at": (
                    entry.published_at.isoformat()
                    if entry.published_at
                    else None
                ),
                "passes_whitelist": wl_ok,
            })
        return preview

    # -- internal helpers ----------------------------------------------------

    async def _parse_feed(self, url: str) -> list[_FeedEntry]:
        """
        Download the feed with httpx (for timeout / UA control) then hand
        the raw bytes to feedparser.  Returns [] on any HTTP or parse error.
        """
        timeout = float(await settings.get("crawler.request_timeout_seconds", 10))
        ua = await settings.get("crawler.user_agent", "BitpinRadar/1.0")

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                follow_redirects=True,
            ) as client:
                resp = await client.get(url, headers={"User-Agent": ua})
                resp.raise_for_status()
                raw_bytes = resp.content
                content_type = resp.headers.get("content-type", "application/rss+xml")
        except httpx.TimeoutException:
            log.warning("rss_poll.feed_timeout", url=url, timeout=timeout)
            return []
        except httpx.HTTPStatusError as exc:
            log.warning(
                "rss_poll.feed_http_error",
                url=url,
                status_code=exc.response.status_code,
            )
            return []
        except httpx.RequestError as exc:
            log.warning("rss_poll.feed_request_error", url=url, error=str(exc))
            return []

        # Pass response headers so feedparser can resolve relative URLs
        # and pick the correct character encoding.
        feed = await asyncio.to_thread(
            feedparser.parse,
            raw_bytes,
            response_headers={
                "content-location": url,
                "content-type": content_type,
            },
        )

        if feed.bozo and not feed.entries:
            log.warning(
                "rss_poll.feed_parse_error",
                url=url,
                bozo_exception=str(feed.get("bozo_exception", "unknown")),
            )
            return []

        return [self._make_entry(e) for e in feed.entries]

    @staticmethod
    def _make_entry(raw: Any) -> _FeedEntry:
        url = (getattr(raw, "link", "") or "").strip()
        title = (getattr(raw, "title", "") or "").strip()

        # Some feeds put content in summary_detail; fall back to summary
        summary: str | None = None
        if hasattr(raw, "summary") and raw.summary:
            summary = raw.summary.strip() or None

        published_at: datetime | None = None
        struct = getattr(raw, "published_parsed", None) or getattr(raw, "updated_parsed", None)
        if struct:
            try:
                published_at = datetime.fromtimestamp(
                    calendar.timegm(struct), tz=timezone.utc
                )
            except (TypeError, OverflowError, OSError):
                pass

        return _FeedEntry(
            url=url,
            title=title,
            summary=summary,
            published_at=published_at,
            raw=raw,
        )

    @staticmethod
    async def _load_due_sources() -> list[Source]:
        global_default = int(await settings.get("crawler.poll_interval_minutes", 15))
        now = datetime.now(tz=timezone.utc)

        async with AsyncSessionLocal() as session:
            rows = list(await session.scalars(
                select(Source)
                .where(Source.is_active.is_(True))
                .order_by(Source.priority.desc(), Source.id)
            ))

        due: list[Source] = []
        for source in rows:
            interval = source.poll_interval_minutes or global_default
            if source.last_polled_at is None:
                due.append(source)
                continue
            elapsed = (now - source.last_polled_at).total_seconds()
            if elapsed >= interval * 60:
                due.append(source)
        return due

    @staticmethod
    async def _record_poll_result(
        source_id: int,
        *,
        status: str,
        new_items: int,
        message: str | None,
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        async with AsyncSessionLocal() as session:
            source = await session.get(Source, source_id)
            if source is not None:
                source.last_polled_at = now
                source.last_poll_status = status
                source.last_poll_new_items = new_items
                source.last_poll_message = message
                await session.commit()

    @staticmethod
    async def _load_active_sources() -> list[Source]:
        async with AsyncSessionLocal() as session:
            rows = await session.scalars(
                select(Source)
                .where(Source.is_active.is_(True))
                .order_by(Source.priority.desc(), Source.id)
            )
            return list(rows)


# ---------------------------------------------------------------------------
# Module-level singleton helper (used by Celery task)
# ---------------------------------------------------------------------------

_poller = RSSPoller()


async def poll_all_sources() -> list[RawNewsItem]:
    """Convenience wrapper; keeps crawl_task.py import unchanged."""
    return await _poller.poll_all_sources()
