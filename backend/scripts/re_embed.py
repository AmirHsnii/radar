"""
Re-embed all categories and coins using batch API calls.

Run this after the DB is seeded (scripts/seed.py) whenever:
- You switch embedding models
- The coin/category list changes and you want fresh vectors

Usage:
    cd backend
    python -m scripts.re_embed            # re-embed everything
    python -m scripts.re_embed --dry-run  # preview without changes
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.embeddings import _CATS_KEY, _COINS_KEY, Embedder, EmbeddingCache
from app.modules.coins.embed_text import coin_embed_text
from app.models.category import Category
from app.models.coin import Coin


async def main(dry_run: bool = False) -> None:
    embedder = Embedder()
    cache = EmbeddingCache(embedder_instance=embedder)

    async with AsyncSessionLocal() as session:
        coins = list(await session.scalars(select(Coin)))
        categories = list(await session.scalars(select(Category)))

    print(f"Found {len(coins)} coins, {len(categories)} categories")

    if dry_run:
        print("\nDry run — no changes made.")
        return

    # --- Coins ---
    if coins:
        coin_texts = [coin_embed_text(c.symbol, c.name, c.aliases) for c in coins]
        print(f"Embedding {len(coins)} coins…")
        coin_vectors = await embedder.embed_batch(coin_texts)

        async with AsyncSessionLocal() as session:
            for coin, vector in zip(coins, coin_vectors):
                obj = await session.get(Coin, coin.id)
                if obj is not None:
                    obj.embedding = vector
            await session.commit()
        print(f"  ✓ {len(coins)} coins updated")

    # --- Categories ---
    if categories:
        cat_texts = [
            f"{c.name_fa} {c.name} {c.description}" for c in categories
        ]
        print(f"Embedding {len(categories)} categories…")
        cat_vectors = await embedder.embed_batch(cat_texts)

        async with AsyncSessionLocal() as session:
            for cat, vector in zip(categories, cat_vectors):
                obj = await session.get(Category, cat.id)
                if obj is not None:
                    obj.embedding = vector
            await session.commit()
        print(f"  ✓ {len(categories)} categories updated")

    # --- Invalidate Redis cache ---
    await cache.invalidate(_COINS_KEY)
    await cache.invalidate(_CATS_KEY)
    print("  ✓ Cache invalidated")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv))
