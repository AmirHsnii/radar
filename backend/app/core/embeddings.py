"""
Embedder — async wrapper around the OpenRouter/OpenAI embedding endpoint.
EmbeddingCache — Redis-backed cache for text vectors and coin/category embeddings.
cosine_similarity — module-level helper used by the classifier.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pickle
from dataclasses import dataclass

import numpy as np
import structlog
from openai import APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from sqlalchemy import select
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis
from app.core.settings_env import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from app.models.category import Category
from app.models.coin import Coin

log = structlog.get_logger(__name__)

_COINS_KEY = "radar:emb:coins"
_CATS_KEY = "radar:emb:cats"
_TEXT_KEY_TPL = "radar:emb:text:{sha}"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CoinEmbedding:
    id: int
    symbol: str
    name: str
    vector: list[float]
    aliases: str | None = None


@dataclass
class CategoryEmbedding:
    id: int
    name: str
    name_fa: str
    vector: list[float]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _pickle_encode(data: object) -> str:
    """Serialize with pickle and base64-encode to a Redis-safe string."""
    return base64.b64encode(pickle.dumps(data)).decode()


def _pickle_decode(s: str) -> object:
    return pickle.loads(base64.b64decode(s))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two float vectors. Returns 0.0 if either is zero."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(va)) * float(np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom else 0.0


# ---------------------------------------------------------------------------
# Retry predicate (same logic as openrouter.py)
# ---------------------------------------------------------------------------

def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (RateLimitError, APITimeoutError)):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        return True
    return False


# ---------------------------------------------------------------------------
# Embedder — API calls with retry
# ---------------------------------------------------------------------------

class Embedder:
    """Wraps the OpenRouter/OpenAI embedding endpoint with retry logic."""

    def __init__(self) -> None:
        # Tests may assign a mock client directly to _oa.
        self._oa: AsyncOpenAI | None = None

    async def _client(self) -> AsyncOpenAI:
        if self._oa is not None:
            return self._oa

        base_url = str(await settings.get("embedding.base_url", "")).strip() or OPENROUTER_BASE_URL
        api_key = str(await settings.get("embedding.api_key", "")).strip() or OPENROUTER_API_KEY
        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": "https://bitpin.ir",
                "X-Title": "Bitpin Radar",
            },
        )

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string (no caching — use EmbeddingCache.embed)."""
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Embed multiple texts in a single API call.
        Returns vectors in the same order as input.
        """
        if not texts:
            return []

        model = str(await settings.get("ai.embedding_model", "text-embedding-3-small"))
        max_retries = int(await settings.get("ai.max_retries", 3))
        timeout = float(await settings.get("ai.timeout_seconds", 30))
        client = await self._client()

        result: list[list[float]] | None = None
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception(_is_retryable),
            reraise=True,
        ):
            with attempt:
                resp = await client.embeddings.create(
                    model=model,
                    input=texts,
                    timeout=timeout,
                )
                result = [
                    item.embedding
                    for item in sorted(resp.data, key=lambda x: x.index)
                ]

        log.debug("embedder.batch_done", count=len(texts), model=model)
        return result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# EmbeddingCache — Redis caching layer
# ---------------------------------------------------------------------------

class EmbeddingCache:
    """
    Redis-backed cache for text vectors and coin/category embedding lists.

    Text vectors: keyed by sha256(text), stored as JSON.
    Coin/Category lists: keyed by constant, stored as base64-encoded pickle.
    """

    def __init__(self, embedder_instance: Embedder | None = None) -> None:
        self._embedder = embedder_instance or Embedder()

    # ------------------------------------------------------------------
    # Text embedding (used by classifier)
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float]:
        """Embed a text string with Redis caching."""
        key = _TEXT_KEY_TPL.format(sha=_sha256(text))
        redis = await get_redis()
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)

        vector = await self._embedder.embed(text)
        ttl = int(await settings.get("embedding.cache_ttl_seconds", 3600))
        await redis.setex(key, ttl, json.dumps(vector))
        return vector

    # ------------------------------------------------------------------
    # Coin / Category lists (loaded from DB, cached in Redis)
    # ------------------------------------------------------------------

    async def get_coins(self) -> list[CoinEmbedding]:
        """Return all coins with embeddings. Redis-cached; falls back to DB."""
        redis = await get_redis()
        cached = await redis.get(_COINS_KEY)
        if cached:
            try:
                return _pickle_decode(cached)  # type: ignore[return-value]
            except Exception:
                log.warning("embedding_cache.coins_pickle_corrupt")

        coins = await self._load_coins_from_db()
        if coins:
            ttl = int(await settings.get("embedding.cache_ttl_seconds", 3600))
            await redis.setex(_COINS_KEY, ttl, _pickle_encode(coins))
        return coins

    async def get_categories(self) -> list[CategoryEmbedding]:
        """Return all categories with embeddings. Redis-cached; falls back to DB."""
        redis = await get_redis()
        cached = await redis.get(_CATS_KEY)
        if cached:
            try:
                return _pickle_decode(cached)  # type: ignore[return-value]
            except Exception:
                log.warning("embedding_cache.cats_pickle_corrupt")

        cats = await self._load_categories_from_db()
        if cats:
            ttl = int(await settings.get("embedding.cache_ttl_seconds", 3600))
            await redis.setex(_CATS_KEY, ttl, _pickle_encode(cats))
        return cats

    async def invalidate(self, key: str) -> None:
        """Delete a cache entry by key."""
        redis = await get_redis()
        await redis.delete(key)

    # ------------------------------------------------------------------
    # DB loaders
    # ------------------------------------------------------------------

    async def _load_coins_from_db(self) -> list[CoinEmbedding]:
        try:
            async with AsyncSessionLocal() as session:
                rows = list(await session.scalars(
                    select(Coin).where(Coin.embedding.isnot(None))
                ))
            return [
                CoinEmbedding(
                    id=c.id,
                    symbol=c.symbol,
                    name=c.name,
                    vector=list(c.embedding),
                    aliases=c.aliases,
                )
                for c in rows
            ]
        except Exception as exc:
            log.warning("embedding_cache.load_coins_failed", error=str(exc))
            return []

    async def _load_categories_from_db(self) -> list[CategoryEmbedding]:
        try:
            async with AsyncSessionLocal() as session:
                rows = list(await session.scalars(
                    select(Category).where(Category.embedding.isnot(None))
                ))
            return [
                CategoryEmbedding(id=c.id, name=c.name, name_fa=c.name_fa,
                                  vector=list(c.embedding))
                for c in rows
            ]
        except Exception as exc:
            log.warning("embedding_cache.load_categories_failed", error=str(exc))
            return []


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

embedder = Embedder()
embedding_cache = EmbeddingCache(embedder_instance=embedder)


async def reset_embedder_client() -> None:
    """Close cached OpenAI client on the embedder singleton."""
    if embedder._oa is not None:
        try:
            await embedder._oa.close()
        except Exception:
            pass
        embedder._oa = None
