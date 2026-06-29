"""
Dedup engine — detects duplicate news articles by title hash.

Two layers:
  1. DedupEngine.is_duplicate(title)  — high-level class; reads settings,
     tracks daily skip metrics. Used by the AI pipeline.
  2. Module-level helpers (url_hash, title_hash, is_duplicate)  — used by
     RSSPoller where the hash is pre-computed and window is passed explicitly.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date

from app.config import settings
from app.core.redis_client import get_redis

_DEDUP_PREFIX = "dedup:"
_METRICS_PREFIX = "dedup:metrics:skipped:"
_METRICS_TTL = 7 * 24 * 3600   # keep 7 days of daily counters


# ---------------------------------------------------------------------------
# Normalisation — public so callers and tests can inspect it
# ---------------------------------------------------------------------------

def normalize(title: str) -> str:
    """
    Canonical form used for dedup comparison:
      1. Unicode NFKC  — collapses compatibility variants (e.g. Arabic forms)
      2. Lowercase
      3. Strip leading/trailing whitespace
      4. Remove all non-word, non-space characters (punctuation, symbols)
      5. Collapse internal whitespace to a single space

    Persian/Arabic word characters are preserved; only punctuation (،؟«»…)
    and symbols are stripped.
    """
    text = unicodedata.normalize("NFKC", title)
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------------------------------------------------------------------------
# DedupEngine
# ---------------------------------------------------------------------------

class DedupEngine:
    """
    Checks whether a news title has already been seen within the configured
    dedup window (dedup.window_hours).

    On first sight  → stores hash in Redis with TTL, returns False.
    On duplicate    → increments the daily skip counter, returns True.
    """

    @staticmethod
    def compute_hash(title: str) -> str:
        """SHA-256 of the normalised title. Always 64 hex characters."""
        return _sha256(normalize(title))

    async def is_duplicate(self, title: str) -> bool:
        window_hours = int(await settings.get("dedup.window_hours", 24))
        h = self.compute_hash(title)

        redis = await get_redis()
        key = f"{_DEDUP_PREFIX}{h}"
        exists = await redis.exists(key)

        if not exists:
            await redis.setex(key, window_hours * 3600, "1")
            return False

        await self._record_skip(redis)
        return True

    async def _record_skip(self, redis) -> None:
        key = f"{_METRICS_PREFIX}{date.today().isoformat()}"
        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, _METRICS_TTL)
        await pipe.execute()

    async def get_skip_count(self, for_date: str | None = None) -> int:
        """Return duplicate-skip count for the given date (YYYY-MM-DD).
        Defaults to today. Returns 0 if no data exists."""
        d = for_date or date.today().isoformat()
        redis = await get_redis()
        val = await redis.get(f"{_METRICS_PREFIX}{d}")
        return int(val) if val else 0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

dedup_engine = DedupEngine()


# ---------------------------------------------------------------------------
# Backward-compatible helpers (used by RSSPoller with pre-computed hashes)
# ---------------------------------------------------------------------------

def url_hash(url: str) -> str:
    return _sha256(url.strip())


def title_hash(title: str) -> str:
    """Normalised SHA-256 of the title (same normalisation as DedupEngine)."""
    return _sha256(normalize(title))


async def is_duplicate(hash_value: str, window_hours: int = 24) -> bool:
    """
    Low-level helper: checks a pre-computed hash (no settings lookup).
    Does NOT record skip metrics — use DedupEngine.is_duplicate for that.
    """
    redis = await get_redis()
    key = f"{_DEDUP_PREFIX}{hash_value}"
    exists = await redis.exists(key)
    if not exists:
        await redis.setex(key, window_hours * 3600, "1")
    return bool(exists)


async def mark_seen(hash_value: str, window_hours: int = 24) -> None:
    """Mark a hash as seen without checking (used after bootstrap ingest)."""
    redis = await get_redis()
    key = f"{_DEDUP_PREFIX}{hash_value}"
    await redis.setex(key, window_hours * 3600, "1")
