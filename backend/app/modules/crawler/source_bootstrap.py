"""Bootstrap a newly created RSS source with its latest feed entries."""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.source import Source
from app.modules.crawler.rss_poller import RSSPoller, RawNewsItem
from app.modules.crawler.whitelist import passes_whitelist
from app.modules.dedup.engine import mark_seen, title_hash, url_hash

log = structlog.get_logger(__name__)


async def bootstrap_source(source_id: int, *, limit: int | None = None) -> list[RawNewsItem]:
    """
    Fetch up to ``limit`` latest whitelist-passing entries for a new source.

    Skips Redis dedup (fresh source) but respects DB uniqueness later in persist.
    Marks URL/title hashes as seen so regular polling only picks up newer items.
    """
    count = limit if limit is not None else int(
        await settings.get("crawler.bootstrap_on_create_count", 5)
    )
    window_hours = int(await settings.get("dedup.window_hours", 24))

    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
    if source is None:
        log.warning("source_bootstrap.source_not_found", source_id=source_id)
        return []

    poller = RSSPoller()
    entries = await poller._parse_feed(source.rss_url)
    if not entries:
        log.info("source_bootstrap.feed_empty", source_id=source_id)
        await RSSPoller._record_poll_result(
            source_id,
            status="empty",
            new_items=0,
            message="bootstrap: فید خالی",
        )
        return []

    items: list[RawNewsItem] = []
    for entry in entries:
        if len(items) >= count:
            break
        if not entry.url or not entry.title:
            continue
        if not passes_whitelist(entry.title, source.language):
            continue

        u_hash = url_hash(entry.url)
        t_hash = title_hash(entry.title)

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
        await mark_seen(u_hash, window_hours)
        await mark_seen(t_hash, window_hours)

    now = datetime.now(tz=timezone.utc)
    async with AsyncSessionLocal() as session:
        src = await session.get(Source, source_id)
        if src is not None:
            src.last_polled_at = now
            src.last_poll_status = "success" if items else "empty"
            src.last_poll_new_items = len(items)
            src.last_poll_message = f"bootstrap: {len(items)} خبر اولیه"
            await session.commit()

    log.info(
        "source_bootstrap.done",
        source_id=source_id,
        picked=len(items),
        limit=count,
    )
    return items
