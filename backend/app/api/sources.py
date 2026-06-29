"""
Sources API — manage RSS feed sources.

Endpoints:
  GET    /api/sources                → list all sources
  POST   /api/sources                → create a new source
  GET    /api/sources/{id}           → get one source
  PUT    /api/sources/{id}           → update a source
  DELETE /api/sources/{id}           → soft delete (is_active=False) or hard delete
  POST   /api/sources/{id}/toggle    → toggle is_active flag
  POST   /api/sources/{id}/test           → trigger a poll for this source, return item count
  POST   /api/sources/{id}/test-pipeline  → ingest latest feed item and run full AI pipeline
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.news import NewsOut
from app.core.database import AsyncSessionLocal
from app.models.news import NewsItem
from app.models.source import Source
from app.modules.dedup.engine import title_hash, url_hash as compute_url_hash

router = APIRouter(prefix="/sources", tags=["sources"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SourceCreate(BaseModel):
    name: str
    rss_url: str
    site_url: str = ""
    language: str = "en"
    is_active: bool = True
    priority: int = 5
    poll_interval_minutes: int | None = None


class SourceUpdate(BaseModel):
    name: str | None = None
    rss_url: str | None = None
    site_url: str | None = None
    language: str | None = None
    is_active: bool | None = None
    priority: int | None = None
    poll_interval_minutes: int | None = None


class SourceOut(BaseModel):
    id: int
    name: str
    rss_url: str
    site_url: str
    language: str
    is_active: bool
    priority: int
    poll_interval_minutes: int | None
    last_polled_at: datetime | None
    last_poll_status: str | None = None
    last_poll_new_items: int | None = None
    last_poll_message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[SourceOut])
async def list_sources(
    is_active: bool | None = Query(None, description="Filter by active status"),
):
    """List all RSS sources."""
    async with AsyncSessionLocal() as session:
        q = select(Source).order_by(Source.priority.desc(), Source.name)
        if is_active is not None:
            q = q.where(Source.is_active == is_active)
        rows = list(await session.scalars(q))
    return rows


@router.post("/", response_model=SourceOut, status_code=201)
async def create_source(body: SourceCreate):
    """Create a new RSS source."""
    async with AsyncSessionLocal() as session:
        existing = await session.scalar(
            select(Source).where(Source.rss_url == body.rss_url)
        )
        if existing:
            raise HTTPException(
                status_code=409, detail="A source with this RSS URL already exists"
            )
        source = Source(**body.model_dump())
        session.add(source)
        await session.commit()
        await session.refresh(source)
        source_id = source.id

    from app.tasks.crawl_task import bootstrap_source_task

    bootstrap_source_task.delay(source_id)
    return source


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(source_id: int):
    """Get a single source by ID."""
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.put("/{source_id}", response_model=SourceOut)
async def update_source(source_id: int, body: SourceUpdate):
    """Update fields of an existing source."""
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        updates = body.model_dump(exclude_unset=True)

        if "rss_url" in updates and updates["rss_url"] != source.rss_url:
            existing = await session.scalar(
                select(Source).where(Source.rss_url == updates["rss_url"])
            )
            if existing:
                raise HTTPException(
                    status_code=409, detail="A source with this RSS URL already exists"
                )

        for field, value in updates.items():
            setattr(source, field, value)

        await session.commit()
        await session.refresh(source)
    return source


@router.delete("/{source_id}", status_code=200)
async def delete_source(
    source_id: int,
    hard: bool = Query(
        False,
        description="If true, permanently delete; otherwise soft delete (is_active=False)",
    ),
):
    """Delete a source. Default is soft delete (sets is_active=False)."""
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")

        if hard:
            await session.delete(source)
            await session.commit()
            return {"deleted": True, "hard": True, "id": source_id}
        else:
            source.is_active = False
            await session.commit()
            return {"deleted": True, "hard": False, "id": source_id, "is_active": False}


@router.post("/{source_id}/toggle", response_model=SourceOut)
async def toggle_source(source_id: int):
    """Toggle the is_active flag for a source."""
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Source not found")
        source.is_active = not source.is_active
        await session.commit()
        await session.refresh(source)
    return source


@router.post("/{source_id}/test")
async def test_source(source_id: int):
    """
    Trigger a one-off poll for this source.
    Returns the number of new items discovered and a preview of up to 20 items.
    """
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    from app.modules.crawler.rss_poller import RSSPoller

    poller = RSSPoller()
    try:
        preview = await poller.preview_feed(source, limit=5)
        items = await poller.poll_source(source)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Poll failed: {exc}") from exc

    return {
        "source_id": source_id,
        "source_name": source.name,
        "feed_entries": len(preview),
        "latest": preview[0] if preview else None,
        "preview": preview,
        "new_items_count": len(items),
        "new_items": [
            {"url": item.url, "title": item.title, "language": item.language}
            for item in items[:20]
        ],
        # backward compat
        "items_discovered": len(items),
        "items": [
            {"url": item.url, "title": item.title, "language": item.language}
            for item in items[:20]
        ],
    }


class SourceTestPipelineOut(BaseModel):
    source_id: int
    source_name: str
    picked: dict
    news_id: int
    success: bool
    error: str | None = None
    news: NewsOut | None = None
    pipeline_stages: list[dict] | None = None


def _parse_published_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _reset_news_for_reprocess(item: NewsItem, *, title: str, title_h: str) -> None:
    item.title = title
    item.title_hash = title_h
    item.content = None
    item.language = None
    item.title_fa = None
    item.summary_fa = None
    item.sentiment = None
    item.coins_json = None
    item.categories_json = None
    item.processed_at = None
    item.processing_cost_usd = None
    item.generation_mode = None
    item.status = "pending"


@router.post("/{source_id}/test-pipeline", response_model=SourceTestPipelineOut)
async def test_source_pipeline(source_id: int):
    """
    Ingest the latest RSS entry (bypassing dedup) and run the full AI pipeline
    synchronously so admins can inspect the processed output in the news list.
    """
    async with AsyncSessionLocal() as session:
        source = await session.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    from app.modules.crawler.rss_poller import RSSPoller

    poller = RSSPoller()
    try:
        preview = await poller.preview_feed(source, limit=1)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Feed fetch failed: {exc}") from exc

    if not preview:
        raise HTTPException(status_code=400, detail="Feed is empty or could not be parsed")

    latest = preview[0]
    from app.modules.crawler.whitelist import passes_whitelist

    if not passes_whitelist(latest["title"], source.language):
        raise HTTPException(
            status_code=400,
            detail="Latest item does not pass the whitelist filter for this source language",
        )

    u_hash = compute_url_hash(latest["url"])
    t_hash = title_hash(latest["title"])
    pub_at = _parse_published_at(latest.get("published_at"))

    async with AsyncSessionLocal() as session:
        item = await session.scalar(
            select(NewsItem).where(NewsItem.url_hash == u_hash)
        )
        if item:
            _reset_news_for_reprocess(item, title=latest["title"], title_h=t_hash)
            item.source_id = source_id
            item.published_at = pub_at
            await session.commit()
            await session.refresh(item)
            news_id = item.id
        else:
            row = NewsItem(
                url=latest["url"],
                url_hash=u_hash,
                title=latest["title"],
                title_hash=t_hash,
                content=None,
                language=source.language,
                source_id=source_id,
                status="pending",
                published_at=pub_at,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            news_id = row.id

    from app.modules.pipeline.orchestrator import append_publish_stage, process_news_item
    from app.tasks.process_task import _get_publish_settings, _set_pending_review

    try:
        success = await process_news_item(news_id)
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            item = await session.get(NewsItem, news_id)
        stages = []
        if item and item.pipeline_stages_json:
            try:
                import json as _json
                stages = _json.loads(item.pipeline_stages_json)
            except Exception:
                pass
        return SourceTestPipelineOut(
            source_id=source_id,
            source_name=source.name,
            picked=latest,
            news_id=news_id,
            success=False,
            error=str(exc),
            news=NewsOut.model_validate(item) if item else None,
            pipeline_stages=stages or None,
        )

    publish_status = "skipped"
    publish_reason: str | None = None
    publish_detail: dict | None = None

    if success:
        auto_publish, manual_review = await _get_publish_settings()
        if manual_review:
            await _set_pending_review(news_id)
            publish_status = "skipped"
            publish_reason = "manual_review_mode"
        elif auto_publish:
            from app.tasks.publish_task import publish_to_wordpress_task
            publish_to_wordpress_task.delay(news_id)
            publish_status = "queued"
            publish_reason = None
            publish_detail = {"task": "tasks.publish_to_wordpress"}
        else:
            publish_status = "skipped"
            publish_reason = "auto_publish_disabled"

    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
        if item and success:
            item.pipeline_stages_json = append_publish_stage(
                item.pipeline_stages_json,
                status=publish_status,
                reason=publish_reason,
                detail=publish_detail,
            )
            await session.commit()
            await session.refresh(item)

    stages: list[dict] = []
    if item and item.pipeline_stages_json:
        try:
            import json as _json
            stages = _json.loads(item.pipeline_stages_json)
        except Exception:
            pass

    if not success:
        return SourceTestPipelineOut(
            source_id=source_id,
            source_name=source.name,
            picked=latest,
            news_id=news_id,
            success=False,
            error=item.status if item else "Pipeline failed",
            news=NewsOut.model_validate(item) if item else None,
            pipeline_stages=stages or None,
        )

    return SourceTestPipelineOut(
        source_id=source_id,
        source_name=source.name,
        picked=latest,
        news_id=news_id,
        success=True,
        news=NewsOut.model_validate(item),
        pipeline_stages=stages or None,
    )
