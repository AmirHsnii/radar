"""
Celery tasks for the crawl stage.

poll_all_sources_task — triggered by Beat every N minutes
  • Polls all active RSS sources via RSSPoller
  • Persists new items to DB (URL-hash dedup as DB-level safety net)
  • Dispatches process_news_item_task for each freshly saved item

retry_dlq_items_task — triggered by Beat every 30 minutes
  • Picks up DLQ items whose next_retry_at has passed
  • Re-dispatches them through the pipeline
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.core.async_runner import run_async
from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.dlq import DeadLetterQueue
from app.models.news import NewsItem
from app.modules.crawler.rss_poller import RawNewsItem, poll_all_sources
from app.modules.crawler.source_bootstrap import bootstrap_source
from app.modules.dedup.engine import url_hash as compute_url_hash

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Task: poll all RSS sources
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.poll_all_sources", max_retries=0)
def poll_all_sources_task() -> dict[str, int]:
    return run_async(_poll())


async def _poll() -> dict[str, int]:
    log.info("crawl_task.poll_started")
    items = await poll_all_sources()

    if not items:
        log.info("crawl_task.no_new_items")
        return {}

    saved = await _persist(items)
    log.info("crawl_task.persisted", discovered=len(items), saved=len(saved))

    from app.tasks.process_task import process_news_item_task

    for news_id in saved.values():
        process_news_item_task.delay(news_id)

    log.info("crawl_task.dispatched", count=len(saved))
    return saved


@celery_app.task(name="tasks.bootstrap_source", max_retries=1)
def bootstrap_source_task(source_id: int) -> dict[str, int]:
    """Ingest latest N feed entries when a new source is created."""
    return run_async(_bootstrap(source_id))


async def _bootstrap(source_id: int) -> dict[str, int]:
    log.info("crawl_task.bootstrap_started", source_id=source_id)
    items = await bootstrap_source(source_id)
    if not items:
        log.info("crawl_task.bootstrap_no_items", source_id=source_id)
        return {}

    saved = await _persist(items)
    log.info("crawl_task.bootstrap_persisted", source_id=source_id, saved=len(saved))

    from app.tasks.process_task import process_news_item_task

    for news_id in saved.values():
        process_news_item_task.delay(news_id)

    log.info("crawl_task.bootstrap_dispatched", source_id=source_id, count=len(saved))
    return saved


# ---------------------------------------------------------------------------
# DB persistence — URL-hash uniqueness enforced at this layer too
# ---------------------------------------------------------------------------

async def _persist(items: list[RawNewsItem]) -> dict[str, int]:
    """
    Insert items not already in the DB.

    Redis dedup in RSSPoller is the first gate; this is a safety net that
    handles Redis restarts, manual test runs, or duplicate URLs across feeds.

    Returns {url: news_id} for every row actually inserted.
    """
    saved: dict[str, int] = {}

    async with AsyncSessionLocal() as session:
        for item in items:
            u_hash = compute_url_hash(item.url)

            # Scalar select — only fetch the id, not the full row
            exists_id = await session.scalar(
                select(NewsItem.id).where(NewsItem.url_hash == u_hash)
            )
            if exists_id is not None:
                log.debug("crawl_task.db_dup_skipped", url=item.url)
                continue

            row = NewsItem(
                url=item.url,
                url_hash=u_hash,
                title=item.title,
                title_hash=item.title_hash,
                content=item.content or None,
                language=item.language,
                source_id=item.source_id,
                status="pending",
                published_at=item.published_at,
            )
            session.add(row)
            await session.flush()   # populate row.id without committing
            saved[item.url] = row.id

        await session.commit()

    return saved


# ---------------------------------------------------------------------------
# Task: retry DLQ items
# ---------------------------------------------------------------------------

@celery_app.task(name="tasks.retry_dlq_items", max_retries=0)
def retry_dlq_items_task() -> int:
    return run_async(_retry_dlq())


async def _retry_dlq() -> int:
    from app.tasks.process_task import process_news_item_task

    now = datetime.now(tz=timezone.utc)

    async with AsyncSessionLocal() as session:
        items = list(await session.scalars(
            select(DeadLetterQueue).where(
                DeadLetterQueue.status == "pending",
                DeadLetterQueue.next_retry_at <= now,
            )
        ))

        if not items:
            log.debug("dlq_retry.nothing_due")
            return 0

        for item in items:
            item.status = "retrying"
        await session.commit()

    dispatched = 0
    for item in items:
        if item.news_id:
            process_news_item_task.delay(item.news_id)
            dispatched += 1

    log.info("dlq_retry.dispatched", count=dispatched, total=len(items))
    return dispatched
