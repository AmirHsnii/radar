"""
DLQ API — dead letter queue management.

Endpoints:
  GET  /api/dlq               → paginated list (optional status filter)
  POST /api/dlq/{id}/retry    → schedule retry for one item
  POST /api/dlq/{id}/discard  → discard one item
  POST /api/dlq/retry-all     → retry all pending items
  GET  /api/dlq/stats         → status breakdown counts
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.dlq import DeadLetterQueue
from app.modules.dlq.manager import dlq_manager

router = APIRouter(prefix="/dlq", tags=["dlq"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class DLQOut(BaseModel):
    id: int
    news_id: int | None
    stage: str
    error_message: str
    retry_count: int
    max_retries: int
    next_retry_at: datetime | None
    resolved_at: datetime | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class DiscardRequest(BaseModel):
    reason: str = ""


class PaginatedDLQ(BaseModel):
    items: list[DLQOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_dlq_stats():
    """Return count breakdown by status."""
    return await dlq_manager.stats()


@router.get("/", response_model=PaginatedDLQ)
async def list_dlq(
    status: str | None = Query(None, description="Filter by status: pending|retrying|exhausted|discarded|resolved"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
):
    """List DLQ items with optional status filter and pagination."""
    offset = (page - 1) * size

    async with AsyncSessionLocal() as session:
        base_q = select(DeadLetterQueue)
        if status:
            base_q = base_q.where(DeadLetterQueue.status == status)

        # Total count
        from sqlalchemy import func
        count_q = select(func.count()).select_from(base_q.subquery())
        total: int = await session.scalar(count_q) or 0

        # Paginated rows
        rows = list(await session.scalars(
            base_q.order_by(DeadLetterQueue.created_at.desc())
                  .offset(offset)
                  .limit(size)
        ))

    return PaginatedDLQ(items=rows, total=total, page=page, size=size)


@router.post("/{dlq_id}/retry", status_code=202)
async def retry_dlq_item(dlq_id: int):
    """Schedule a specific DLQ item for re-processing."""
    found = await dlq_manager.retry(dlq_id)
    if not found:
        raise HTTPException(status_code=404, detail="DLQ item not found")
    return {"queued": True, "dlq_id": dlq_id}


@router.post("/{dlq_id}/discard", status_code=200)
async def discard_dlq_item(dlq_id: int, body: DiscardRequest = DiscardRequest()):
    """Discard a DLQ item — it will not be retried again."""
    found = await dlq_manager.discard(dlq_id, reason=body.reason)
    if not found:
        raise HTTPException(status_code=404, detail="DLQ item not found")
    return {"discarded": True, "dlq_id": dlq_id}


@router.post("/retry-all", status_code=202)
async def retry_all_pending():
    """Retry all pending DLQ items whose next_retry_at has passed."""
    items = await dlq_manager.get_pending_retries()
    queued_ids: list[int] = []
    for item in items:
        success = await dlq_manager.retry(item.id)
        if success:
            queued_ids.append(item.id)
    return {"queued_count": len(queued_ids), "dlq_ids": queued_ids}
