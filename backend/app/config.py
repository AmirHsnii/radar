"""
DB-backed dynamic settings with Redis cache.

Usage:
    from app.config import settings
    value = await settings.get("ai.fast_model", "google/gemini-flash-1.5")
    await settings.set("ai.batch_size", 10, updated_by="admin")
    await settings.refresh("ai.batch_size")   # invalidate cache
"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.settings import AppSetting

# ---------------------------------------------------------------------------
# Default values — mirrors migration 0001 seed; used by /api/settings/defaults
# tuple: (default_value_str, value_type, description)
# ---------------------------------------------------------------------------
SETTING_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "crawler.poll_interval_minutes":   ("15",    "int",   "فاصله پیش‌فرض پولینگ RSS (دقیقه) — برای منابع بدون مقدار اختصاصی"),
    "crawler.beat_tick_minutes":       ("1",     "int",   "فاصله بررسی Celery Beat برای منابع سررسید (دقیقه)"),
    "crawler.request_timeout_seconds": ("10",    "int",   "HTTP timeout for content fetch"),
    "crawler.max_content_length":      ("5000",  "int",   "Max characters of article content to process"),
    "crawler.user_agent":              ("Mozilla/5.0 (compatible; BitpinRadar/1.0; +https://bitpin.ir)", "str", "User-Agent header for HTTP requests"),
    "crawler.whitelist_keywords_fa":   ("null",  "json",  "JSON list of FA whitelist keywords (required for Persian sources)"),
    "crawler.whitelist_keywords_en":   ("[]",    "json",  "JSON list of EN whitelist keywords (optional; empty = allow all EN)"),
    "dedup.window_hours":              ("24",    "int",   "Dedup time window in hours"),
    "dedup.method":                    ("hash",  "str",   "Dedup method: hash | fuzzy"),
    "ai.fast_model":                   ("google/gemini-flash-1.5", "str", "Cheap model for translation and summary"),
    "ai.quality_model":                ("openai/gpt-4o-mini",      "str", "Better model for retries and difficult content"),
    "ai.batch_size":                   ("5",     "int",   "News items per LLM batch call"),
    "ai.max_retries":                  ("3",     "int",   "Max LLM call retries on error"),
    "ai.timeout_seconds":              ("30",    "int",   "LLM request timeout in seconds"),
    "ai.summary_max_tokens":           ("150",   "int",   "Max tokens for summary output"),
    "ai.translation_max_tokens":       ("2000",  "int",   "Max tokens for translation output"),
    "cost.monthly_budget_usd":         ("50",    "float", "Monthly LLM spend budget in USD"),
    "cost.alert_threshold_pct":        ("80",    "int",   "Alert when monthly spend exceeds this % of budget"),
    "publisher.auto_publish":          ("false", "bool",  "Auto-publish to WordPress after pipeline completes"),
    "publisher.wp_batch_size":         ("10",    "int",   "WordPress posts per publish batch"),
    "wp.url":                          ("",      "str",    "آدرس سایت WordPress (مثال: https://example.com)"),
    "wp.username":                     ("",      "str",    "نام کاربری وردپرس"),
    "wp.app_password":                 ("",      "secret", "Application Password وردپرس"),
    "wp.request_timeout_seconds":      ("30",    "int",   "WordPress HTTP request timeout"),
    "wp.max_retries":                  ("3",     "int",   "WordPress publish retry attempts"),
    "classifier.category_threshold":   ("0.65",  "float", "Min cosine similarity to assign a category"),
    "classifier.coin_threshold":       ("0.65",  "float", "Min cosine similarity to tag a coin (with keyword fallback)"),
    "classifier.default_category":     ("اخبار بازار", "str",   "Fallback category when no match found"),
    "classifier.keyword_match_enabled": ("true", "bool",  "Match coins by symbol/name/alias in text"),
    "classifier.semantic_enabled":     ("true",  "bool",  "Use embedding cosine similarity for coins/categories"),
    "classifier.max_classify_chars":   ("1500",  "int",   "Max characters sent to embedding classifier"),
    "classifier.content_snippet_chars": ("800",  "int",   "Content excerpt length for classification"),
    "crawler.bootstrap_on_create_count": ("5",    "int",   "Latest feed items to ingest when a source is created"),
    "ai.embedding_model":              ("text-embedding-3-small", "str", "مدل embedding برای دسته‌بندی و تگ کوین (OpenRouter/OpenAI)"),
    "embedding.base_url":              ("", "str",    "Base URL سرویس embedding — خالی = OPENROUTER_BASE_URL"),
    "embedding.api_key":               ("", "secret", "API Key سرویس embedding — خالی = OPENROUTER_API_KEY"),
    "embedding.cache_ttl_seconds":     ("3600",  "int",   "Redis TTL for embedding cache entries"),
    "pipeline.manual_review_mode":     ("false", "bool",  "If true, processed news waits for manual approval before publishing"),
    # Per-agent overrides — empty string means "use global default"
    "agent.translator.model":          ("", "str",    "مدل ترجمه‌کننده — خالی = ai.fast_model"),
    "agent.translator.base_url":       ("", "str",    "Base URL ترجمه‌کننده — خالی = OPENROUTER_BASE_URL"),
    "agent.translator.api_key":        ("", "secret", "API Key ترجمه‌کننده — خالی = OPENROUTER_API_KEY"),
    "agent.summarizer.model":          ("", "str",    "مدل خلاصه‌ساز — خالی = ai.fast_model"),
    "agent.summarizer.base_url":       ("", "str",    "Base URL خلاصه‌ساز"),
    "agent.summarizer.api_key":        ("", "secret", "API Key خلاصه‌ساز"),
    "agent.sentiment.model":           ("", "str",    "مدل آنالیز احساسات — خالی = ai.fast_model"),
    "agent.sentiment.base_url":        ("", "str",    "Base URL آنالیز احساسات"),
    "agent.sentiment.api_key":         ("", "secret", "API Key آنالیز احساسات"),
    "agent.translator.prompt":         ("", "text",   "پرامپت سیستم ترجمه‌کننده — خالی = پیش‌فرض"),
    "agent.summarizer.prompt":         ("", "text",   "پرامپت سیستم خلاصه‌ساز — خالی = پیش‌فرض"),
    "agent.sentiment.prompt":          ("", "text",   "پرامپت سیستم آنالیز احساسات — خالی = پیش‌فرض"),
    "agent.router.prompt":             ("", "text",   "پرامپت تشخیص زبان (Router) — خالی = پیش‌فرض"),
    "agent.summarizer_fa.prompt":      ("", "text",   "پرامپت خلاصه‌ساز فارسی — خالی = پیش‌فرض"),
}

# ---------------------------------------------------------------------------
# Type casting
# ---------------------------------------------------------------------------
_CASTS: dict[str, Any] = {
    "str":   str,
    "text":  str,
    "int":   int,
    "float": float,
    "bool":  lambda v: v.strip().lower() in ("true", "1", "yes"),
    "json":  json.loads,
}

_INFER: list[tuple[type, str, Any]] = [
    (bool,  "bool",  lambda v: str(v).lower()),
    (int,   "int",   str),
    (float, "float", str),
    (dict,  "json",  json.dumps),
    (list,  "json",  json.dumps),
]


def _cast(raw: str, value_type: str) -> Any:
    fn = _CASTS.get(value_type, str)
    return fn(raw)


def _infer_type(value: Any) -> tuple[str, str]:
    """Return (value_type, str_value) for any Python value."""
    for py_type, vtype, serialise in _INFER:
        if isinstance(value, py_type):
            return vtype, serialise(value)
    return "str", str(value)


# ---------------------------------------------------------------------------
# Settings class
# ---------------------------------------------------------------------------
_CACHE_PREFIX = "radar:settings:"
_DEFAULT_TTL = int(os.getenv("SETTINGS_CACHE_TTL", "300"))


class Settings:
    """
    Async settings manager backed by PostgreSQL with Redis cache.

    All cache/DB access is funnelled through small protected methods so unit
    tests can patch them without touching real infrastructure.
    """

    def __init__(self, cache_ttl: int = _DEFAULT_TTL) -> None:
        self._ttl = cache_ttl

    # -- cache helpers (patchable in tests) ----------------------------------

    async def _cache_get(self, key: str) -> str | None:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        return await redis.get(f"{_CACHE_PREFIX}{key}")

    async def _cache_set(self, key: str, payload: str) -> None:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        await redis.setex(f"{_CACHE_PREFIX}{key}", self._ttl, payload)

    async def _cache_delete(self, key: str) -> None:
        from app.core.redis_client import get_redis
        redis = await get_redis()
        await redis.delete(f"{_CACHE_PREFIX}{key}")

    # -- DB helpers (patchable in tests) -------------------------------------

    async def _db_get(self, key: str) -> AppSetting | None:
        async with AsyncSessionLocal() as session:
            return await session.scalar(
                select(AppSetting).where(AppSetting.key == key)
            )

    async def _db_upsert(
        self,
        key: str,
        value: str,
        value_type: str,
        updated_by: str,
    ) -> AppSetting:
        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(AppSetting).where(AppSetting.key == key)
            )
            if row:
                row.value = value
                row.value_type = value_type
                row.updated_by = updated_by
            else:
                default_desc = SETTING_DEFAULTS.get(key, ("", "", ""))[2]
                row = AppSetting(
                    key=key,
                    value=value,
                    value_type=value_type,
                    updated_by=updated_by,
                    description=default_desc,
                )
                session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def _db_all(self) -> list[AppSetting]:
        async with AsyncSessionLocal() as session:
            rows = await session.scalars(select(AppSetting).order_by(AppSetting.key))
            return list(rows)

    # -- public API ----------------------------------------------------------

    async def get(self, key: str, default: Any = None) -> Any:
        """Return typed value for key; hits Redis first, then DB."""
        # 1. cache hit
        raw = await self._cache_get(key)
        if raw is not None:
            data = json.loads(raw)
            return _cast(data["v"], data["t"])

        # 2. DB lookup
        row = await self._db_get(key)
        if row is None:
            return default

        # 3. populate cache
        await self._cache_set(key, json.dumps({"v": row.value, "t": row.value_type}))
        return _cast(row.value, row.value_type)

    async def set(
        self,
        key: str,
        value: Any,
        updated_by: str = "system",
        *,
        value_type: str | None = None,
    ) -> None:
        """Persist a new value and invalidate its cache entry."""
        inferred_type, str_value = _infer_type(value)
        effective_type = value_type or inferred_type
        await self._db_upsert(
            key=key,
            value=str_value,
            value_type=effective_type,
            updated_by=updated_by,
        )
        await self._cache_delete(key)

    async def refresh(self, key: str) -> None:
        """Invalidate the Redis cache for a single key."""
        await self._cache_delete(key)

    async def prefetch_all(self) -> int:
        """
        Warm the cache with all settings from DB.
        Call at application startup to avoid per-request DB round-trips.
        """
        rows = await self._db_all()
        for row in rows:
            payload = json.dumps({"v": row.value, "t": row.value_type})
            await self._cache_set(row.key, payload)
        return len(rows)

    async def get_all(self) -> list[AppSetting]:
        """Return all rows ordered by key (for admin listing)."""
        return await self._db_all()


# ---------------------------------------------------------------------------
# Singleton + FastAPI dependency
# ---------------------------------------------------------------------------
settings = Settings()


async def get_settings() -> Settings:
    """FastAPI dependency — returns the process-wide Settings singleton."""
    return settings
