"""
DLQManager — higher-level interface over the dead_letter_queue table.

Exponential back-off delays:
  retry 0 → 5 min
  retry 1 → 15 min
  retry 2 → 45 min
  retry 3+ → 60 min
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.dlq import DeadLetterQueue

log = structlog.get_logger(__name__)

_BACKOFF_MINUTES: list[int] = [5, 15, 45, 60]


def _next_retry_delta(retry_count: int) -> timedelta:
    idx = min(retry_count, len(_BACKOFF_MINUTES) - 1)
    return timedelta(minutes=_BACKOFF_MINUTES[idx])


class DLQManager:

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    async def send(
        self,
        news_id: int | None,
        stage: str,
        error: str,
        retry_count: int = 0,
    ) -> None:
        """Create a new DLQ entry with exponential back-off timing."""
        from app.config import settings  # lazy to avoid circular import

        max_retries: int = int(await settings.get("dlq.max_retries", 3))
        now = datetime.now(tz=timezone.utc)
        next_retry = now + _next_retry_delta(retry_count)
        status = "pending" if retry_count < max_retries else "exhausted"

        async with AsyncSessionLocal() as session:
            session.add(DeadLetterQueue(
                news_id=news_id,
                stage=stage,
                error_message=error[:2000],
                retry_count=retry_count,
                max_retries=max_retries,
                next_retry_at=next_retry,
                status=status,
            ))
            await session.commit()

        log.info(
            "dlq_manager.sent",
            news_id=news_id, stage=stage,
            retry_count=retry_count, status=status,
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_pending_retries(self) -> list[DeadLetterQueue]:
        """Return all pending DLQ items whose next_retry_at is in the past."""
        now = datetime.now(tz=timezone.utc)
        async with AsyncSessionLocal() as session:
            rows = list(await session.scalars(
                select(DeadLetterQueue).where(
                    DeadLetterQueue.status == "pending",
                    DeadLetterQueue.next_retry_at <= now,
                ).order_by(DeadLetterQueue.next_retry_at)
            ))
        return rows

    # ------------------------------------------------------------------
    # Action helpers
    # ------------------------------------------------------------------

    async def retry(self, dlq_id: int) -> bool:
        """
        Schedule the associated news item for processing and mark as retrying.
        Returns True if the item was found and queued, False otherwise.
        """
        from app.tasks.process_task import process_news_item_task  # lazy

        async with AsyncSessionLocal() as session:
            item = await session.get(DeadLetterQueue, dlq_id)
            if not item:
                log.warning("dlq_manager.retry_not_found", dlq_id=dlq_id)
                return False

            item.status = "retrying"
            await session.commit()

        if item.news_id:
            process_news_item_task.delay(item.news_id)
            log.info("dlq_manager.retry_queued", dlq_id=dlq_id, news_id=item.news_id)

        return True

    async def discard(self, dlq_id: int, reason: str = "") -> bool:
        """
        Mark a DLQ item as discarded (will not be retried).
        Returns True if the item was found, False otherwise.
        """
        async with AsyncSessionLocal() as session:
            item = await session.get(DeadLetterQueue, dlq_id)
            if not item:
                log.warning("dlq_manager.discard_not_found", dlq_id=dlq_id)
                return False

            item.status = "discarded"
            if reason:
                item.error_message = f"{item.error_message}\n[DISCARDED] {reason}"[:2000]
            item.resolved_at = datetime.now(tz=timezone.utc)
            await session.commit()

        log.info("dlq_manager.discarded", dlq_id=dlq_id, reason=reason)
        return True

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def stats(self) -> dict[str, Any]:
        """Return count breakdown by status."""
        async with AsyncSessionLocal() as session:
            rows = await session.execute(
                select(
                    DeadLetterQueue.status,
                    func.count().label("cnt"),
                ).group_by(DeadLetterQueue.status)
            )
            breakdown: dict[str, int] = {r.status: r.cnt for r in rows}

        total = sum(breakdown.values())
        return {
            "total":     total,
            "pending":   breakdown.get("pending",   0),
            "retrying":  breakdown.get("retrying",  0),
            "exhausted": breakdown.get("exhausted", 0),
            "discarded": breakdown.get("discarded", 0),
            "resolved":  breakdown.get("resolved",  0),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

dlq_manager = DLQManager()
