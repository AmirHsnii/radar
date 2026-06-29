from __future__ import annotations

import structlog

from app.core.async_runner import run_async
from app.core.celery_app import celery_app
from app.modules.pipeline.orchestrator import process_news_item

log = structlog.get_logger(__name__)


@celery_app.task(
    name="tasks.process_news_item",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def process_news_item_task(self, news_id: int, retry_count: int = 0) -> bool:
    """
    AI pipeline task: fetch → route → translate/summarize → classify.
    On success: schedules publish_to_wordpress.
    On failure: item is sent to DLQ inside process_news_item().
    """
    try:
        return run_async(_process_and_finalize(news_id))
    except Exception as exc:
        log.error("process_task.unexpected_error", news_id=news_id, error=str(exc))
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


async def _process_and_finalize(news_id: int) -> bool:
    success = await process_news_item(news_id)
    if success:
        await _after_process(news_id)
    return success


async def _after_process(news_id: int) -> None:
    from app.tasks.publish_task import publish_to_wordpress_task
    from app.modules.pipeline.orchestrator import append_publish_stage
    from app.core.database import AsyncSessionLocal
    from app.models.news import NewsItem

    auto_publish, manual_review = await _get_publish_settings()
    publish_status = "skipped"
    publish_reason: str | None = None
    publish_detail: dict | None = None

    if manual_review:
        await _set_pending_review(news_id)
        publish_reason = "manual_review_mode"
        log.info("process_task.pending_review", news_id=news_id)
    elif auto_publish:
        publish_to_wordpress_task.delay(news_id)
        publish_status = "queued"
        publish_detail = {"task": "tasks.publish_to_wordpress"}
        log.info("process_task.publish_queued", news_id=news_id)
    else:
        publish_reason = "auto_publish_disabled"

    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
        if item:
            item.pipeline_stages_json = append_publish_stage(
                item.pipeline_stages_json,
                status=publish_status,
                reason=publish_reason,
                detail=publish_detail,
            )
            await session.commit()


async def _get_publish_settings() -> tuple[bool, bool]:
    from app.config import settings
    auto_publish = bool(await settings.get("publisher.auto_publish", False))
    manual_review = bool(await settings.get("pipeline.manual_review_mode", False))
    return auto_publish, manual_review


async def _set_pending_review(news_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.news import NewsItem
    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
        if item:
            item.status = "pending_review"
            await session.commit()
