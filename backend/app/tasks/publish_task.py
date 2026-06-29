from __future__ import annotations

import json

import structlog

from app.core.async_runner import run_async
from app.core.celery_app import celery_app

log = structlog.get_logger(__name__)


@celery_app.task(
    name="tasks.publish_to_wordpress",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    acks_late=True,
)
def publish_to_wordpress_task(self, news_id: int) -> int | None:
    """Publish a classified news item to WordPress."""
    try:
        return run_async(_publish(news_id))
    except Exception as exc:
        log.error("publish_task.failed", news_id=news_id, error=str(exc))
        raise self.retry(exc=exc, countdown=120 * (2 ** self.request.retries))


async def _publish(news_id: int) -> int | None:
    from app.core.database import AsyncSessionLocal
    from app.models.news import NewsItem
    from app.models.source import Source
    from app.modules.dlq import send_to_dlq
    from app.modules.publisher.wordpress import wordpress_publisher

    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
        if not item or item.status not in ("classified", "translated", "summarized", "pending_review"):
            log.warning("publish_task.skipped", news_id=news_id,
                        status=item.status if item else "not_found")
            return None

        source_name: str | None = None
        if item.source_id:
            source = await session.get(Source, item.source_id)
            if source:
                source_name = source.name

        try:
            result = await wordpress_publisher.publish(
                title=item.title_fa or item.title or "",
                summary_fa=item.summary_fa or "",
                categories=json.loads(item.categories_json or "[]"),
                coins=json.loads(item.coins_json or "[]"),
                sentiment=item.sentiment,
                news_id=item.id,
                source_name=source_name,
                generation_mode=item.generation_mode,
            )
            item.wp_post_id = result.post_id
            item.status = "published"
            await session.commit()
            log.info("publish_task.done", news_id=news_id, post_id=result.post_id)
            return result.post_id

        except Exception as exc:
            item.retry_count += 1
            item.status = "failed"
            await session.commit()
            await send_to_dlq(
                item_id=item.id,
                stage="publish",
                error=str(exc),
                retry_count=item.retry_count,
            )
            raise
