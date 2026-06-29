"""
WhitelistFilter — keyword-based relevance gate for FA and EN news sources.

FA keywords: required for Persian sources (title must match).
EN keywords: optional — empty list means all English news pass.
"""
from __future__ import annotations

import asyncio
import json

import structlog

from app.config import settings
from app.modules.dedup.engine import normalize as _normalize

log = structlog.get_logger(__name__)

_DEFAULT_FA_KEYWORDS: list[str] = [
    "بیتکوین", "اتریوم", "ارز دیجیتال", "بلاکچین",
    "کریپتو", "دیفای", "توکن", "کیف پول", "صرافی", "رمزارز",
    "رمز ارز", "ارزهای دیجیتال",
]

_DEFAULT_EN_KEYWORDS: list[str] = []

_SETTINGS_KEY_FA = "crawler.whitelist_keywords_fa"
_SETTINGS_KEY_EN = "crawler.whitelist_keywords_en"
_LEGACY_KEY = "crawler.whitelist_keywords"


class WhitelistFilter:
    """Checks whether a news title matches language-specific keyword lists."""

    def __init__(self) -> None:
        self._keywords_fa: list[str] | None = None
        self._keywords_en: list[str] | None = None
        self._lock = asyncio.Lock()

    async def _load_fa(self) -> list[str]:
        raw = await settings.get(_SETTINGS_KEY_FA, None)
        if raw is None:
            raw = await settings.get(_LEGACY_KEY, None)
        if raw is None:
            return list(_DEFAULT_FA_KEYWORDS)
        return self._parse_keywords(raw, _DEFAULT_FA_KEYWORDS)

    async def _load_en(self) -> list[str]:
        raw = await settings.get(_SETTINGS_KEY_EN, None)
        if raw is None:
            return list(_DEFAULT_EN_KEYWORDS)
        return self._parse_keywords(raw, _DEFAULT_EN_KEYWORDS)

    @staticmethod
    def _parse_keywords(raw: object, fallback: list[str]) -> list[str]:
        if isinstance(raw, list):
            return [str(k) for k in raw]
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(k) for k in parsed]
            except Exception:
                pass
        return list(fallback)

    async def _get_keywords_fa(self) -> list[str]:
        if self._keywords_fa is None:
            async with self._lock:
                if self._keywords_fa is None:
                    self._keywords_fa = await self._load_fa()
        return self._keywords_fa

    async def _get_keywords_en(self) -> list[str]:
        if self._keywords_en is None:
            async with self._lock:
                if self._keywords_en is None:
                    self._keywords_en = await self._load_en()
        return self._keywords_en

    async def reload(self) -> tuple[int, int]:
        """Force re-read from settings. Returns (fa_count, en_count)."""
        async with self._lock:
            self._keywords_fa = await self._load_fa()
            self._keywords_en = await self._load_en()
        fa_count = len(self._keywords_fa)
        en_count = len(self._keywords_en)
        log.info("whitelist.reloaded", fa_count=fa_count, en_count=en_count)
        return fa_count, en_count

    async def passes(self, title: str, language: str = "fa") -> bool:
        """Return True if title passes the whitelist for the given source language."""
        norm_title = _normalize(title)
        if language == "fa":
            keywords = await self._get_keywords_fa()
            return any(_normalize(kw) in norm_title for kw in keywords)
        keywords = await self._get_keywords_en()
        if not keywords:
            return True
        return any(_normalize(kw) in norm_title for kw in keywords)

    def passes_sync(self, title: str, language: str = "fa") -> bool:
        """Synchronous check using cached or default keywords."""
        norm_title = _normalize(title)
        if language == "fa":
            keywords = (
                self._keywords_fa if self._keywords_fa is not None
                else _DEFAULT_FA_KEYWORDS
            )
            return any(_normalize(kw) in norm_title for kw in keywords)
        keywords = (
            self._keywords_en if self._keywords_en is not None
            else _DEFAULT_EN_KEYWORDS
        )
        if not keywords:
            return True
        return any(_normalize(kw) in norm_title for kw in keywords)

    async def _load(self) -> list[str]:
        """Backward-compatible: returns FA keywords."""
        return await self._get_keywords_fa()


whitelist_filter = WhitelistFilter()


def passes_whitelist(text: str, language: str = "fa") -> bool:
    """Synchronous whitelist gate used by rss_poller."""
    return whitelist_filter.passes_sync(text, language)
