"""
News API — browse and inspect processed news items.

Endpoints:
  GET /api/news        → list with filters: status, source_id, language,
                         coin, category, date_from, date_to; pagination
  GET /api/news/stats  → daily stats: {total, by_status, by_language}
  GET /api/news/{id}   → get one news item with all fields
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.news import NewsItem

router = APIRouter(prefix="/news", tags=["news"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class NewsOut(BaseModel):
    id: int
    url: str
    title: str | None
    title_fa: str | None
    summary_fa: str | None
    content: str | None
    language: str | None
    source_id: int | None
    status: str
    retry_count: int
    sentiment: str | None
    coins_json: str | None
    categories_json: str | None
    wp_post_id: int | None
    processing_cost_usd: float | None
    pipeline_stages_json: str | None = None
    generation_mode: str | None = None
    created_at: datetime
    processed_at: datetime | None
    published_at: datetime | None

    class Config:
        from_attributes = True


class NewsListOut(BaseModel):
    items: list[NewsOut]
    total: int
    page: int
    size: int


# ---------------------------------------------------------------------------
# Routes — note: /stats MUST be declared before /{id} to avoid routing clash
# ---------------------------------------------------------------------------

@router.get("/stats")
async def news_stats(
    date_str: str | None = Query(
        None,
        description="ISO date (YYYY-MM-DD) to filter; defaults to today",
    ),
):
    """
    Daily stats for a given date: total items, breakdown by status and language.
    """
    if date_str:
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_str must be ISO format YYYY-MM-DD")
    else:
        d = date.today()

    day_start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    day_end = datetime(d.year, d.month, d.day + 1 if d.day < 31 else 1,
                       tzinfo=timezone.utc) if d.month < 12 or d.day < 31 else datetime(
        d.year + 1, 1, 1, tzinfo=timezone.utc
    )
    # Simpler approach using timedelta
    from datetime import timedelta
    day_end = day_start + timedelta(days=1)

    async with AsyncSessionLocal() as session:
        total: int = await session.scalar(
            select(func.count(NewsItem.id)).where(
                NewsItem.created_at >= day_start,
                NewsItem.created_at < day_end,
            )
        ) or 0

        status_rows = await session.execute(
            select(NewsItem.status, func.count().label("cnt"))
            .where(
                NewsItem.created_at >= day_start,
                NewsItem.created_at < day_end,
            )
            .group_by(NewsItem.status)
        )
        by_status = {r.status: r.cnt for r in status_rows}

        lang_rows = await session.execute(
            select(NewsItem.language, func.count().label("cnt"))
            .where(
                NewsItem.created_at >= day_start,
                NewsItem.created_at < day_end,
            )
            .group_by(NewsItem.language)
        )
        by_language = {(r.language or "unknown"): r.cnt for r in lang_rows}

    return {
        "date": d.isoformat(),
        "total": total,
        "by_status": by_status,
        "by_language": by_language,
    }


@router.get("/", response_model=NewsListOut)
async def list_news(
    status: str | None = Query(None, description="Filter by pipeline status"),
    source_id: int | None = Query(None, description="Filter by source ID"),
    language: str | None = Query(None, description="Filter by language: en|fa"),
    coin: str | None = Query(None, description="Filter by coin symbol substring in coins_json"),
    category: str | None = Query(None, description="Filter by category substring in categories_json"),
    date_from: str | None = Query(None, description="ISO date from (inclusive), e.g. 2024-01-01"),
    date_to: str | None = Query(None, description="ISO date to (exclusive), e.g. 2024-01-31"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    """List news items with optional filters and pagination."""
    offset = (page - 1) * size

    filters = []
    if status:
        filters.append(NewsItem.status == status)
    if source_id is not None:
        filters.append(NewsItem.source_id == source_id)
    if language:
        filters.append(NewsItem.language == language)
    if coin:
        filters.append(NewsItem.coins_json.ilike(f"%{coin}%"))
    if category:
        filters.append(NewsItem.categories_json.ilike(f"%{category}%"))
    if date_from:
        try:
            df = datetime.fromisoformat(date_from) if "T" in date_from else datetime(
                *map(int, date_from.split("-")), tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid date_from format")
        filters.append(NewsItem.created_at >= df)
    if date_to:
        try:
            dt = datetime.fromisoformat(date_to) if "T" in date_to else datetime(
                *map(int, date_to.split("-")), tzinfo=timezone.utc
            )
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid date_to format")
        filters.append(NewsItem.created_at < dt)

    async with AsyncSessionLocal() as session:
        count_q = select(func.count(NewsItem.id))
        if filters:
            count_q = count_q.where(*filters)
        total: int = await session.scalar(count_q) or 0

        list_q = select(NewsItem)
        if filters:
            list_q = list_q.where(*filters)
        rows = list(await session.scalars(
            list_q.order_by(NewsItem.created_at.desc())
                  .offset(offset)
                  .limit(size)
        ))

    return NewsListOut(items=rows, total=total, page=page, size=size)


@router.get("/{news_id}", response_model=NewsOut)
async def get_news_item(news_id: int):
    """Get a single news item by ID with all fields."""
    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
    if not item:
        raise HTTPException(status_code=404, detail="News item not found")
    return item


# ---------------------------------------------------------------------------
# Manual review endpoints
# ---------------------------------------------------------------------------

@router.get("/{news_id}/wp-preview")
async def wp_preview(
    news_id: int,
    resolve_ids: bool = Query(False, description="Resolve WP category/tag IDs (requires WP credentials)"),
):
    """
    Returns the exact payload that would be sent to WordPress for this item.
    Used by the admin UI to preview before approving publication.
    """
    import json as _json

    from app.models.source import Source
    from app.modules.publisher.wordpress import wordpress_publisher

    try:
        async with AsyncSessionLocal() as session:
            item = await session.get(NewsItem, news_id)
            if not item:
                raise HTTPException(status_code=404, detail="News item not found")
            source_name: str | None = None
            if item.source_id:
                source = await session.get(Source, item.source_id)
                if source:
                    source_name = source.name

        coins: list[str] = []
        categories: list[str] = []
        try:
            coins = _json.loads(item.coins_json or "[]")
        except Exception:
            pass
        try:
            categories = _json.loads(item.categories_json or "[]")
        except Exception:
            pass

        payload = await wordpress_publisher.build_post_payload(
            title=item.title_fa or item.title or "",
            summary_fa=item.summary_fa or "",
            categories=categories,
            coins=coins,
            sentiment=item.sentiment,
            news_id=item.id,
            source_name=source_name,
            resolve_ids=resolve_ids,
            generation_mode=item.generation_mode,
        )

        return {
            "payload": payload,
            "_ui": {
                "source_name": source_name,
                "source_url": item.url,
                "source_title": item.title,
                "language": item.language,
                "processing_cost_usd": item.processing_cost_usd,
                "current_status": item.status,
                "generation_mode": item.generation_mode,
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"WP preview failed: {exc}",
        ) from exc


@router.post("/{news_id}/approve")
async def approve_news(news_id: int):
    """Approve a pending_review item — triggers WordPress publish."""
    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
        if not item:
            raise HTTPException(status_code=404, detail="News item not found")
        if item.status not in ("pending_review", "classified", "failed"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve item with status '{item.status}'",
            )

    from app.tasks.publish_task import publish_to_wordpress_task
    publish_to_wordpress_task.delay(news_id)
    return {"queued": True, "news_id": news_id}


@router.post("/{news_id}/reject")
async def reject_news(news_id: int):
    """Reject a pending_review item — marks it as rejected, won't publish."""
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
        if not item:
            raise HTTPException(status_code=404, detail="News item not found")
        item.status = "rejected"
        item.processed_at = datetime.now(tz=timezone.utc)
        await session.commit()
    return {"rejected": True, "news_id": news_id}
