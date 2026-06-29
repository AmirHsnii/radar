"""
Unit tests for Embedder, EmbeddingCache, and cosine_similarity.

No real API or Redis calls — everything is mocked.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.embeddings import (
    CategoryEmbedding,
    CoinEmbedding,
    Embedder,
    EmbeddingCache,
    _CATS_KEY,
    _COINS_KEY,
    _pickle_decode,
    _pickle_encode,
    cosine_similarity,
)


# ===========================================================================
# cosine_similarity
# ===========================================================================

class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert cosine_similarity([1.0, 0.0], [0.0, 0.0]) == 0.0

    def test_non_unit_vectors_normalised(self):
        # [3,4] and [6,8] point the same direction — similarity should be 1
        assert cosine_similarity([3.0, 4.0], [6.0, 8.0]) == pytest.approx(1.0)


# ===========================================================================
# _pickle_encode / _pickle_decode round-trip
# ===========================================================================

class TestPickleHelpers:
    def test_roundtrip_list_of_dataclasses(self):
        data = [CoinEmbedding(1, "BTC", "Bitcoin", [0.1, 0.2])]
        assert _pickle_decode(_pickle_encode(data)) == data

    def test_roundtrip_empty_list(self):
        assert _pickle_decode(_pickle_encode([])) == []


# ===========================================================================
# Embedder
# ===========================================================================

def _make_embed_response(vectors: list[list[float]]):
    items = []
    for i, vec in enumerate(vectors):
        item = MagicMock()
        item.index = i
        item.embedding = vec
        items.append(item)
    resp = MagicMock()
    resp.data = items
    return resp


def _mock_settings(*keys_and_defaults):
    """Patch settings.get to return values from a dict."""
    defaults = {
        "ai.embedding_model": "text-embedding-3-small",
        "ai.max_retries": 3,
        "ai.timeout_seconds": 30,
        "embedding.cache_ttl_seconds": 3600,
    }
    async def _get(key, default=None):
        return defaults.get(key, default)
    return _get


class TestEmbedder:
    @pytest.mark.asyncio
    async def test_embed_batch_returns_vectors(self):
        vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        resp = _make_embed_response(vectors)

        embedder = Embedder()
        embedder._oa = MagicMock()
        embedder._oa.embeddings = MagicMock()
        embedder._oa.embeddings.create = AsyncMock(return_value=resp)

        with patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(side_effect=_mock_settings())
            result = await embedder.embed_batch(["hello", "world"])

        assert result == vectors

    @pytest.mark.asyncio
    async def test_embed_batch_empty_input(self):
        embedder = Embedder()
        assert await embedder.embed_batch([]) == []

    @pytest.mark.asyncio
    async def test_embed_delegates_to_batch(self):
        vector = [0.1, 0.2]
        resp = _make_embed_response([vector])

        embedder = Embedder()
        embedder._oa = MagicMock()
        embedder._oa.embeddings = MagicMock()
        embedder._oa.embeddings.create = AsyncMock(return_value=resp)

        with patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(side_effect=_mock_settings())
            result = await embedder.embed("test")

        assert result == vector

    @pytest.mark.asyncio
    async def test_embed_batch_orders_by_index(self):
        """Items returned out of order should be sorted by .index."""
        item0 = MagicMock(); item0.index = 0; item0.embedding = [1.0]
        item1 = MagicMock(); item1.index = 1; item1.embedding = [2.0]
        resp = MagicMock()
        resp.data = [item1, item0]   # reversed

        embedder = Embedder()
        embedder._oa = MagicMock()
        embedder._oa.embeddings = MagicMock()
        embedder._oa.embeddings.create = AsyncMock(return_value=resp)

        with patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(side_effect=_mock_settings())
            result = await embedder.embed_batch(["a", "b"])

        assert result == [[1.0], [2.0]]


# ===========================================================================
# EmbeddingCache.embed (text caching)
# ===========================================================================

class TestEmbeddingCacheEmbed:
    @pytest.mark.asyncio
    async def test_returns_cached_vector(self):
        cached_vector = [0.9, 0.8, 0.7]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps(cached_vector))

        mock_embedder = MagicMock()
        mock_embedder.embed = AsyncMock()

        cache = EmbeddingCache(embedder_instance=mock_embedder)

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)), \
             patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(return_value=3600)
            result = await cache.embed("hello")

        assert result == cached_vector
        mock_embedder.embed.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_api_on_cache_miss_and_stores(self):
        vector = [0.1, 0.2]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        mock_embedder = MagicMock()
        mock_embedder.embed = AsyncMock(return_value=vector)

        cache = EmbeddingCache(embedder_instance=mock_embedder)

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)), \
             patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(return_value=3600)
            result = await cache.embed("hello")

        assert result == vector
        mock_redis.setex.assert_called_once()
        _key, ttl, payload = mock_redis.setex.call_args[0]
        assert ttl == 3600
        assert json.loads(payload) == vector


# ===========================================================================
# EmbeddingCache.get_coins
# ===========================================================================

class TestEmbeddingCacheGetCoins:
    @pytest.mark.asyncio
    async def test_returns_cached_coins(self):
        coins = [CoinEmbedding(1, "BTC", "Bitcoin", [0.1, 0.2])]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_pickle_encode(coins))

        cache = EmbeddingCache()

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await cache.get_coins()

        assert result == coins

    @pytest.mark.asyncio
    async def test_loads_from_db_on_cache_miss(self):
        coins = [CoinEmbedding(1, "ETH", "Ethereum", [0.3, 0.4])]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        cache = EmbeddingCache()
        cache._load_coins_from_db = AsyncMock(return_value=coins)

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)), \
             patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(return_value=3600)
            result = await cache.get_coins()

        assert result == coins
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_corrupt_pickle_falls_back_to_db(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="NOTVALIDBASE64!!!!")
        mock_redis.setex = AsyncMock()

        coins = [CoinEmbedding(2, "SOL", "Solana", [0.5])]
        cache = EmbeddingCache()
        cache._load_coins_from_db = AsyncMock(return_value=coins)

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)), \
             patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(return_value=3600)
            result = await cache.get_coins()

        assert result == coins

    @pytest.mark.asyncio
    async def test_empty_db_skips_redis_write(self):
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        cache = EmbeddingCache()
        cache._load_coins_from_db = AsyncMock(return_value=[])

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await cache.get_coins()

        assert result == []
        mock_redis.setex.assert_not_called()


# ===========================================================================
# EmbeddingCache.get_categories
# ===========================================================================

class TestEmbeddingCacheGetCategories:
    @pytest.mark.asyncio
    async def test_returns_cached_categories(self):
        cats = [CategoryEmbedding(1, "DeFi", "دیفای", [0.7, 0.8])]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=_pickle_encode(cats))

        cache = EmbeddingCache()

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)):
            result = await cache.get_categories()

        assert result == cats

    @pytest.mark.asyncio
    async def test_loads_from_db_on_cache_miss(self):
        cats = [CategoryEmbedding(2, "NFT", "NFT", [0.1])]
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.setex = AsyncMock()

        cache = EmbeddingCache()
        cache._load_categories_from_db = AsyncMock(return_value=cats)

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)), \
             patch("app.core.embeddings.settings") as ms:
            ms.get = AsyncMock(return_value=3600)
            result = await cache.get_categories()

        assert result == cats
        mock_redis.setex.assert_called_once()


# ===========================================================================
# EmbeddingCache.invalidate
# ===========================================================================

class TestEmbeddingCacheInvalidate:
    @pytest.mark.asyncio
    async def test_deletes_coins_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        cache = EmbeddingCache()

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)):
            await cache.invalidate(_COINS_KEY)

        mock_redis.delete.assert_called_once_with(_COINS_KEY)

    @pytest.mark.asyncio
    async def test_deletes_cats_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        cache = EmbeddingCache()

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)):
            await cache.invalidate(_CATS_KEY)

        mock_redis.delete.assert_called_once_with(_CATS_KEY)

    @pytest.mark.asyncio
    async def test_deletes_custom_key(self):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        cache = EmbeddingCache()
        custom = "radar:emb:text:abc123"

        with patch("app.core.embeddings.get_redis", new=AsyncMock(return_value=mock_redis)):
            await cache.invalidate(custom)

        mock_redis.delete.assert_called_once_with(custom)


# ===========================================================================
# Module-level singletons
# ===========================================================================

class TestSingletons:
    def test_embedder_singleton_exists(self):
        from app.core.embeddings import embedder
        assert isinstance(embedder, Embedder)

    def test_embedding_cache_singleton_exists(self):
        from app.core.embeddings import embedding_cache
        assert isinstance(embedding_cache, EmbeddingCache)

    def test_cache_uses_shared_embedder(self):
        from app.core.embeddings import embedder, embedding_cache
        assert embedding_cache._embedder is embedder
