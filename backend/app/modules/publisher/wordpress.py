"""
WordPressPublisher — publishes ProcessedNews to WordPress via REST API.

Auth: Application Password (Basic Auth)
Cache: category and tag IDs cached in Redis (avoid repeat taxonomy lookups)
Retry: up to wp.max_retries on timeout/5xx
"""
from __future__ import annotations

import base64
from dataclasses import dataclass

import httpx
import structlog

from app.config import settings
from app.core.redis_client import get_redis
from app.core.settings_env import WP_APP_PASSWORD, WP_URL, WP_USERNAME

log = structlog.get_logger(__name__)

SUMMARY_ONLY_LABEL_FA = (
    "این خبر به‌صورت خودکار تولید شده و فقط خلاصه (summary) است — "
    "متن کامل صفحه منبع در دسترس نبود."
)

_CAT_CACHE_KEY = "radar:wp:cat:{name}"
_TAG_CACHE_KEY = "radar:wp:tag:{name}"
_CACHE_TTL = 60 * 60 * 24  # 24 hours


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class PublishResult:
    post_id: int
    url: str
    status: str


# ---------------------------------------------------------------------------
# Config helpers — DB-backed with .env fallback
# ---------------------------------------------------------------------------

async def _wp_credentials() -> tuple[str, str, str]:
    url = str(await settings.get("wp.url", "")) or WP_URL
    username = str(await settings.get("wp.username", "")) or WP_USERNAME
    password = str(await settings.get("wp.app_password", "")) or WP_APP_PASSWORD
    return url.rstrip("/"), username, password


async def _auth_header() -> str:
    _, username, password = await _wp_credentials()
    credentials = f"{username}:{password}"
    token = base64.b64encode(credentials.encode()).decode()
    return f"Basic {token}"


async def _request_headers() -> dict[str, str]:
    return {
        "Authorization": await _auth_header(),
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# WordPressPublisher
# ---------------------------------------------------------------------------

class WordPressPublisher:
    """Publishes news to WordPress with category/tag resolution and retry."""

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout)

    async def build_post_payload(
        self,
        *,
        title: str,
        summary_fa: str,
        categories: list[str] | None = None,
        coins: list[str] | None = None,
        sentiment: str | None = None,
        news_id: int | None = None,
        source_name: str | None = None,
        resolve_ids: bool = True,
        generation_mode: str | None = None,
    ) -> dict:
        """Build the exact JSON body that would be POSTed to WordPress."""
        summary_only = generation_mode == "summary_only"
        content = _build_content(summary_fa, summary_only=summary_only)

        payload: dict = {
            "title": title,
            "content": content,
            "status": "publish",
        }

        if resolve_ids:
            cat_ids: list[int] = []
            if categories:
                for name in categories:
                    try:
                        cid = await self.ensure_category(name)
                    except Exception as exc:
                        log.warning("wordpress.preview_category_skip", name=name, error=str(exc))
                        cid = None
                    if cid:
                        cat_ids.append(cid)
            if cat_ids:
                payload["categories"] = cat_ids

            tag_ids: list[int] = []
            if coins:
                for symbol in coins:
                    try:
                        tid = await self.ensure_tag(symbol)
                    except Exception as exc:
                        log.warning("wordpress.preview_tag_skip", name=symbol, error=str(exc))
                        tid = None
                    if tid:
                        tag_ids.append(tid)
            if tag_ids:
                payload["tags"] = tag_ids
        else:
            if categories:
                payload["categories"] = categories
            if coins:
                payload["tags"] = coins

        meta = _build_meta(
            coins=coins or [],
            sentiment=sentiment,
            news_id=news_id,
            source_name=source_name,
            generation_mode=generation_mode,
        )
        if meta:
            payload["meta"] = meta

        return payload

    async def publish(
        self,
        title: str,
        summary_fa: str,
        categories: list[str] | None = None,
        coins: list[str] | None = None,
        sentiment: str | None = None,
        news_id: int | None = None,
        source_name: str | None = None,
        source_url: str | None = None,  # noqa: ARG002 — kept for backward compat
        generation_mode: str | None = None,
    ) -> PublishResult:
        """
        Publish a news item to WordPress.

        Content: Farsi summary only (no source link).
        Meta: coins, sentiment, news_id, source_name.
        """
        timeout = float(await settings.get("wp.request_timeout_seconds", 30))
        max_retries = int(await settings.get("wp.max_retries", 3))
        base_url, _, _ = await _wp_credentials()
        headers = await _request_headers()

        payload = await self.build_post_payload(
            title=title,
            summary_fa=summary_fa,
            categories=categories,
            coins=coins,
            sentiment=sentiment,
            news_id=news_id,
            source_name=source_name,
            resolve_ids=True,
            generation_mode=generation_mode,
        )

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                async with self._client(timeout) as client:
                    resp = await client.post(
                        f"{base_url}/wp-json/wp/v2/posts",
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    log.info("wordpress.published",
                             news_id=news_id, post_id=data["id"], attempt=attempt)
                    return PublishResult(
                        post_id=data["id"],
                        url=data.get("link", ""),
                        status=data.get("status", "publish"),
                    )
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_exc = exc
                log.warning("wordpress.retry",
                            news_id=news_id, attempt=attempt, error=str(exc))

        raise RuntimeError(
            f"WordPress publish failed after {max_retries} retries"
        ) from last_exc

    async def ensure_category(self, name: str) -> int | None:
        """Return WordPress category ID for name, creating it if needed."""
        key = _CAT_CACHE_KEY.format(name=name)
        try:
            redis = await get_redis()
            cached = await redis.get(key)
            if cached:
                return int(cached)
        except Exception as exc:
            log.warning("wordpress.redis_cache_read_failed", key=key, error=str(exc))

        timeout = float(await settings.get("wp.request_timeout_seconds", 30))
        base_url, _, _ = await _wp_credentials()
        if not base_url:
            return None
        headers = await _request_headers()
        try:
            async with self._client(timeout) as client:
                resp = await client.get(
                    f"{base_url}/wp-json/wp/v2/categories",
                    headers=headers,
                    params={"search": name, "per_page": 1},
                )
                resp.raise_for_status()
                items = resp.json()
                if items:
                    cid = items[0]["id"]
                else:
                    resp2 = await client.post(
                        f"{base_url}/wp-json/wp/v2/categories",
                        headers=headers,
                        json={"name": name},
                    )
                    resp2.raise_for_status()
                    cid = resp2.json()["id"]

            await redis.setex(key, _CACHE_TTL, str(cid))
            log.debug("wordpress.category_resolved", name=name, id=cid)
            return cid
        except Exception as exc:
            log.warning("wordpress.ensure_category_failed", name=name, error=str(exc))
            return None

    async def ensure_tag(self, name: str) -> int | None:
        """Return WordPress tag ID for name, creating it if needed."""
        key = _TAG_CACHE_KEY.format(name=name)
        try:
            redis = await get_redis()
            cached = await redis.get(key)
            if cached:
                return int(cached)
        except Exception as exc:
            log.warning("wordpress.redis_cache_read_failed", key=key, error=str(exc))

        timeout = float(await settings.get("wp.request_timeout_seconds", 30))
        base_url, _, _ = await _wp_credentials()
        if not base_url:
            return None
        headers = await _request_headers()
        try:
            async with self._client(timeout) as client:
                resp = await client.get(
                    f"{base_url}/wp-json/wp/v2/tags",
                    headers=headers,
                    params={"search": name, "per_page": 1},
                )
                resp.raise_for_status()
                items = resp.json()
                if items:
                    tid = items[0]["id"]
                else:
                    resp2 = await client.post(
                        f"{base_url}/wp-json/wp/v2/tags",
                        headers=headers,
                        json={"name": name},
                    )
                    resp2.raise_for_status()
                    tid = resp2.json()["id"]

            await redis.setex(key, _CACHE_TTL, str(tid))
            log.debug("wordpress.tag_resolved", name=name, id=tid)
            return tid
        except Exception as exc:
            log.warning("wordpress.ensure_tag_failed", name=name, error=str(exc))
            return None


# ---------------------------------------------------------------------------
# Content + meta helpers
# ---------------------------------------------------------------------------

def _build_content(summary_fa: str, *, summary_only: bool = False) -> str:
    """Builds the post body: optional auto-summary notice + summary paragraph."""
    parts: list[str] = []
    if summary_only:
        parts.append(
            '<p class="radar-auto-summary-notice" style="background:#fff8e6;'
            'border-right:4px solid #faad14;padding:8px 12px;margin-bottom:1em;">'
            f"<strong>{SUMMARY_ONLY_LABEL_FA}</strong></p>"
        )
    parts.append(f"<p>{summary_fa}</p>")
    return "".join(parts)


def _build_meta(
    coins: list[str],
    sentiment: str | None,
    news_id: int | None,
    source_name: str | None = None,
    generation_mode: str | None = None,
) -> dict:
    meta: dict = {}
    if coins:
        meta["radar_coins"] = ",".join(coins)
    if sentiment:
        meta["radar_sentiment"] = sentiment
    if news_id is not None:
        meta["radar_news_id"] = str(news_id)
    if source_name:
        meta["radar_source_name"] = source_name
    if generation_mode:
        meta["radar_generation_mode"] = generation_mode
    return meta


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

wordpress_publisher = WordPressPublisher()


# ---------------------------------------------------------------------------
# Backward-compatible function (used by old publish_task)
# ---------------------------------------------------------------------------

async def publish_post(
    title: str,
    content: str,
    status: str = "publish",
    categories: list[int] | None = None,
    tags: list[int] | None = None,
) -> int:
    """Legacy wrapper — creates a post and returns post ID."""
    timeout = float(await settings.get("wp.request_timeout_seconds", 30))
    base_url, _, _ = await _wp_credentials()
    headers = await _request_headers()
    payload: dict = {"title": title, "content": content, "status": status}
    if categories:
        payload["categories"] = categories
    if tags:
        payload["tags"] = tags

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url}/wp-json/wp/v2/posts",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["id"]
