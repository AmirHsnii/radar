"""
Admin API — coins, categories, whitelist, and embedding cache management.

Endpoints:
  GET  /api/admin/coins               → list all coins from DB
  POST /api/admin/coins/re-embed      → re-embed all coins (background task)
  GET  /api/admin/categories          → list all categories from DB
  POST /api/admin/categories/re-embed → re-embed all categories (background task)
  GET  /api/admin/whitelist           → get current whitelist keywords
  PUT  /api/admin/whitelist           → update whitelist keywords
  POST /api/admin/cache/invalidate    → invalidate embedding cache (coins + categories)
"""
from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.embeddings import _CATS_KEY, _COINS_KEY, Embedder, embedding_cache
from app.modules.admin.csv_import import parse_category_csv, parse_coin_csv, parse_whitelist_csv
from app.modules.coins.embed_text import aliases_to_json, coin_embed_text, parse_aliases_value
from app.models.category import Category
from app.models.coin import Coin

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CoinOut(BaseModel):
    id: int
    symbol: str
    name: str
    aliases: list[str]
    has_embedding: bool
    updated_at: datetime

    class Config:
        from_attributes = True


def _coin_out(c: Coin) -> CoinOut:
    return CoinOut(
        id=c.id,
        symbol=c.symbol,
        name=c.name,
        aliases=parse_aliases_value(c.aliases),
        has_embedding=c.embedding is not None,
        updated_at=c.updated_at,
    )


class CategoryOut(BaseModel):
    id: int
    name: str
    name_fa: str
    description: str
    has_embedding: bool
    updated_at: datetime

    class Config:
        from_attributes = True


class WhitelistOut(BaseModel):
    keywords: list[str]
    count: int


class DualWhitelistOut(BaseModel):
    fa_keywords: list[str]
    en_keywords: list[str]
    fa_count: int
    en_count: int


class WhitelistUpdate(BaseModel):
    keywords: list[str]


class DualWhitelistUpdate(BaseModel):
    fa_keywords: list[str]
    en_keywords: list[str]


# ---------------------------------------------------------------------------
# Background re-embed helpers
# ---------------------------------------------------------------------------

async def _re_embed_coins() -> None:
    """Re-embed all coins and invalidate the cache."""
    log.info("admin.re_embed_coins.started")
    embedder = Embedder()

    async with AsyncSessionLocal() as session:
        coins = list(await session.scalars(select(Coin)))

    if not coins:
        log.info("admin.re_embed_coins.no_coins")
        return

    coin_texts = [
        coin_embed_text(c.symbol, c.name, c.aliases) for c in coins
    ]
    try:
        vectors = await embedder.embed_batch(coin_texts)
    except Exception as exc:
        log.error("admin.re_embed_coins.failed", error=str(exc))
        return

    async with AsyncSessionLocal() as session:
        for coin, vector in zip(coins, vectors):
            obj = await session.get(Coin, coin.id)
            if obj is not None:
                obj.embedding = vector
        await session.commit()

    await embedding_cache.invalidate(_COINS_KEY)
    log.info("admin.re_embed_coins.done", count=len(coins))


async def _re_embed_categories() -> None:
    """Re-embed all categories and invalidate the cache."""
    log.info("admin.re_embed_categories.started")
    embedder = Embedder()

    async with AsyncSessionLocal() as session:
        categories = list(await session.scalars(select(Category)))

    if not categories:
        log.info("admin.re_embed_categories.no_categories")
        return

    cat_texts = [f"{c.name_fa} {c.name} {c.description}" for c in categories]
    try:
        vectors = await embedder.embed_batch(cat_texts)
    except Exception as exc:
        log.error("admin.re_embed_categories.failed", error=str(exc))
        return

    async with AsyncSessionLocal() as session:
        for cat, vector in zip(categories, vectors):
            obj = await session.get(Category, cat.id)
            if obj is not None:
                obj.embedding = vector
        await session.commit()

    await embedding_cache.invalidate(_CATS_KEY)
    log.info("admin.re_embed_categories.done", count=len(categories))


# ---------------------------------------------------------------------------
# Routes — coins
# ---------------------------------------------------------------------------

@router.get("/coins", response_model=list[CoinOut])
async def list_coins():
    """List all coins stored in the database."""
    async with AsyncSessionLocal() as session:
        rows = list(await session.scalars(select(Coin).order_by(Coin.symbol)))
    return [_coin_out(c) for c in rows]


@router.post("/coins/re-embed", status_code=202)
async def re_embed_coins(background_tasks: BackgroundTasks):
    """Trigger re-embedding of all coins in the background."""
    background_tasks.add_task(_re_embed_coins)
    from sqlalchemy import func
    async with AsyncSessionLocal() as session:
        total: int = await session.scalar(
            select(func.count(Coin.id))
        ) or 0
    return {"queued": True, "coins_count": total}


@router.post("/coins/import")
async def import_coins_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    re_embed: bool = Query(True, description="Re-embed coins after import"),
):
    """
    Import coins from CSV.

    Columns: symbol, name, aliases (optional)
    aliases: comma-separated nicknames — e.g. «بیت‌کوین, Bitcoin, digital gold»
    Upserts by symbol. Aliases enrich semantic embedding for coin detection.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="فایل خالی است")

    rows = parse_coin_csv(raw)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="هیچ ردیف معتبری یافت نشد. ستون‌ها: symbol, name, aliases",
        )

    created = updated = 0
    async with AsyncSessionLocal() as session:
        for row in rows:
            existing = await session.scalar(
                select(Coin).where(Coin.symbol == row.symbol)
            )
            aliases_json = aliases_to_json(row.aliases)
            if existing:
                existing.name = row.name
                existing.aliases = aliases_json
                existing.embedding = None
                updated += 1
            else:
                session.add(Coin(
                    symbol=row.symbol,
                    name=row.name,
                    aliases=aliases_json,
                ))
                created += 1
        await session.commit()

    await embedding_cache.invalidate(_COINS_KEY)
    if re_embed:
        background_tasks.add_task(_re_embed_coins)

    return {
        "imported": len(rows),
        "created": created,
        "updated": updated,
        "re_embed_queued": re_embed,
    }


# ---------------------------------------------------------------------------
# Routes — categories
# ---------------------------------------------------------------------------

@router.get("/categories", response_model=list[CategoryOut])
async def list_categories():
    """List all categories stored in the database."""
    async with AsyncSessionLocal() as session:
        rows = list(await session.scalars(select(Category).order_by(Category.name)))
    return [
        CategoryOut(
            id=c.id,
            name=c.name,
            name_fa=c.name_fa,
            description=c.description,
            has_embedding=c.embedding is not None,
            updated_at=c.updated_at,
        )
        for c in rows
    ]


@router.post("/categories/re-embed", status_code=202)
async def re_embed_categories(background_tasks: BackgroundTasks):
    """Trigger re-embedding of all categories in the background."""
    background_tasks.add_task(_re_embed_categories)
    async with AsyncSessionLocal() as session:
        from sqlalchemy import func
        total: int = await session.scalar(
            select(func.count(Category.id))
        ) or 0
    return {"queued": True, "categories_count": total}


# ---------------------------------------------------------------------------
# Routes — whitelist
# ---------------------------------------------------------------------------

@router.get("/whitelist", response_model=DualWhitelistOut)
async def get_whitelist():
    """Return FA (required) and EN (optional) whitelist keywords."""
    from app.modules.crawler.whitelist import whitelist_filter

    fa_keywords = await whitelist_filter._load_fa()
    en_keywords = await whitelist_filter._load_en()
    return DualWhitelistOut(
        fa_keywords=fa_keywords,
        en_keywords=en_keywords,
        fa_count=len(fa_keywords),
        en_count=len(en_keywords),
    )


@router.put("/whitelist", response_model=DualWhitelistOut)
async def update_whitelist(body: DualWhitelistUpdate):
    """
    Replace FA and/or EN whitelist keyword lists.
    Saves to app_settings and reloads the in-memory filter.
    """
    from app.config import settings
    from app.modules.crawler.whitelist import whitelist_filter

    await settings.set(
        "crawler.whitelist_keywords_fa",
        body.fa_keywords,
        updated_by="api",
    )
    await settings.set(
        "crawler.whitelist_keywords_en",
        body.en_keywords,
        updated_by="api",
    )
    fa_count, en_count = await whitelist_filter.reload()
    return DualWhitelistOut(
        fa_keywords=body.fa_keywords,
        en_keywords=body.en_keywords,
        fa_count=fa_count,
        en_count=en_count,
    )


# ---------------------------------------------------------------------------
# Routes — cache
# ---------------------------------------------------------------------------

@router.post("/cache/invalidate")
async def invalidate_embedding_cache():
    """Invalidate the Redis embedding cache for coins and categories."""
    await embedding_cache.invalidate(_COINS_KEY)
    await embedding_cache.invalidate(_CATS_KEY)
    log.info("admin.cache.invalidated")
    return {"invalidated": True}


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------

@router.post("/categories/import")
async def import_categories_csv(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    re_embed: bool = Query(True, description="Re-embed categories after import"),
):
    """
    Import categories from CSV.

    Columns: name, name_fa, description (header optional).
    Upserts by English name.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="فایل خالی است")

    rows = parse_category_csv(raw)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="هیچ ردیف معتبری یافت نشد. ستون‌ها: name, name_fa, description",
        )

    created = updated = 0
    async with AsyncSessionLocal() as session:
        for row in rows:
            existing = await session.scalar(
                select(Category).where(Category.name == row.name)
            )
            if existing:
                existing.name_fa = row.name_fa
                existing.description = row.description
                existing.embedding = None
                updated += 1
            else:
                session.add(Category(
                    name=row.name,
                    name_fa=row.name_fa,
                    description=row.description,
                ))
                created += 1
        await session.commit()

    await embedding_cache.invalidate(_CATS_KEY)
    if re_embed:
        background_tasks.add_task(_re_embed_categories)

    return {
        "imported": len(rows),
        "created": created,
        "updated": updated,
        "re_embed_queued": re_embed,
    }


@router.post("/whitelist/import")
async def import_whitelist_csv(
    file: UploadFile = File(...),
    mode: str = Query("merge", description="merge | replace"),
    language: str = Query("fa", description="fa | en"),
):
    """
    Import whitelist keywords from CSV (one keyword per row).

    mode=merge adds new keywords; mode=replace replaces the entire list.
    language=fa updates Persian whitelist; language=en updates English whitelist.
    """
    if mode not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="mode must be merge or replace")
    if language not in ("fa", "en"):
        raise HTTPException(status_code=400, detail="language must be fa or en")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="فایل خالی است")

    imported = parse_whitelist_csv(raw)
    if not imported:
        raise HTTPException(status_code=400, detail="هیچ کلمه‌ای در فایل یافت نشد")

    from app.config import settings
    from app.modules.crawler.whitelist import whitelist_filter

    setting_key = (
        "crawler.whitelist_keywords_fa" if language == "fa"
        else "crawler.whitelist_keywords_en"
    )

    if mode == "merge":
        current = (
            await whitelist_filter._load_fa() if language == "fa"
            else await whitelist_filter._load_en()
        )
        keywords = list(dict.fromkeys([*current, *imported]))
    else:
        keywords = imported

    await settings.set(setting_key, keywords, updated_by="api")
    fa_count, en_count = await whitelist_filter.reload()

    return {
        "imported": len(imported),
        "total": fa_count if language == "fa" else en_count,
        "mode": mode,
        "language": language,
    }
