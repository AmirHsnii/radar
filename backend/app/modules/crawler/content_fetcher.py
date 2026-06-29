"""
ContentFetcher — extracts full article text from a URL.

Strategy (in order):
  1. trafilatura.extract  — best for news sites
  2. newspaper3k          — fallback for trafilatura misses
  3. Returns ""           — never raises, never returns None

All I/O is async; sync extractors run in a thread via asyncio.to_thread().
"""
from __future__ import annotations

import asyncio
import re

import httpx
import structlog
import trafilatura

from app.config import settings

log = structlog.get_logger(__name__)

_DEFAULT_UA = "Mozilla/5.0 (compatible; BitpinRadar/1.0; +https://bitpin.ir)"


def _clean(text: str) -> str:
    """Collapse whitespace: multi-spaces → one space, 3+ newlines → 2."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class ContentFetcher:
    """
    Fetches and extracts article text.

    Returns "" when content cannot be extracted — callers must handle this
    gracefully (e.g. skip processing or use RSS summary instead).
    """

    async def fetch(self, url: str) -> str:
        timeout = int(await settings.get("crawler.request_timeout_seconds", 10))
        max_len = int(await settings.get("crawler.max_content_length", 5000))
        ua = str(await settings.get("crawler.user_agent", _DEFAULT_UA))

        html = await self._download(url, timeout=timeout, ua=ua)
        if not html:
            return ""

        text = await self._extract_trafilatura(html)
        if not text:
            text = await self._extract_newspaper(url, html)
        if not text:
            log.debug("content_fetcher.no_content", url=url)
            return ""

        text = _clean(text)
        return text[:max_len]

    # ------------------------------------------------------------------
    # Internal helpers — small methods make unit testing straightforward
    # ------------------------------------------------------------------

    async def _download(self, url: str, *, timeout: int, ua: str) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": ua},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
        except Exception as exc:
            log.debug("content_fetcher.download_failed", url=url, error=str(exc))
            return ""

    async def _extract_trafilatura(self, html: str) -> str:
        try:
            result = await asyncio.to_thread(
                trafilatura.extract,
                html,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            return result or ""
        except Exception as exc:
            log.debug("content_fetcher.trafilatura_failed", error=str(exc))
            return ""

    async def _extract_newspaper(self, url: str, html: str) -> str:
        try:
            text = await asyncio.to_thread(self._parse_newspaper, url, html)
            return text
        except Exception as exc:
            log.debug("content_fetcher.newspaper_failed", url=url, error=str(exc))
            return ""

    @staticmethod
    def _parse_newspaper(url: str, html: str) -> str:
        from newspaper import Article  # lazy — optional dependency
        art = Article(url)
        art.set_html(html)
        art.parse()
        return art.text or ""


# ---------------------------------------------------------------------------
# Module-level singleton + convenience wrapper
# ---------------------------------------------------------------------------

content_fetcher = ContentFetcher()


async def fetch_content(url: str) -> str:
    """Convenience wrapper — use this in tasks/pipeline code."""
    return await content_fetcher.fetch(url)
