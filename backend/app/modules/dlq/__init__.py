from __future__ import annotations
from datetime import datetime, timedelta, timezone

from app.core.database import AsyncSessionLocal
from app.models.dlq import DeadLetterQueue


async def send_to_dlq(
    item_id: int | None,
    stage: str,
    error: str,
    retry_count: int = 0,
    max_retries: int = 3,
) -> None:
    delay_minutes = 5 * (2 ** retry_count)  # exponential back-off
    next_retry = datetime.now(tz=timezone.utc) + timedelta(minutes=delay_minutes)
    status = "pending" if retry_count < max_retries else "exhausted"

    async with AsyncSessionLocal() as session:
        session.add(DeadLetterQueue(
            news_id=item_id,
            stage=stage,
            error_message=error[:2000],
            retry_count=retry_count,
            max_retries=max_retries,
            next_retry_at=next_retry,
            status=status,
        ))
        await session.commit()
