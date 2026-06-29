"""
Seeder script — run once after `alembic upgrade head`.

Usage:
    cd backend
    python -m scripts.seed              # insert rows only
    python -m scripts.seed --embeddings # also generate embeddings (needs API key)
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import select

# ── Data ────────────────────────────────────────────────────────────────────

# From AGENTS.md § ClassifierAgent — CategoryTagger
DEFAULT_CATEGORIES: list[dict] = [
    {
        "name": "بازار",
        "name_fa": "بازار",
        "description": "قیمت، نوسانات، آمار بازار کریپتو",
    },
    {
        "name": "DeFi",
        "name_fa": "دیفای",
        "description": "امور مالی غیرمتمرکز، yield farming، liquidity pool، پروتکل وام",
    },
    {
        "name": "NFT",
        "name_fa": "NFT",
        "description": "توکن‌های غیرمثلی، هنر دیجیتال، metaverse، بازی بلاکچین",
    },
    {
        "name": "رگولاتوری",
        "name_fa": "رگولاتوری",
        "description": "قوانین، مقررات دولتی، SEC، CFTC، قانون‌گذاری، ممنوعیت",
    },
    {
        "name": "فناوری",
        "name_fa": "فناوری",
        "description": "بلاکچین، پروتکل، upgrade، hard fork، soft fork، توسعه، Layer 2",
    },
    {
        "name": "مایننگ",
        "name_fa": "مایننگ",
        "description": "استخراج، hashrate، ماینر، proof of work، انرژی، ASIC",
    },
    {
        "name": "امنیت",
        "name_fa": "امنیت",
        "description": "هک، exploit، حمله، آسیب‌پذیری، امنیت، smart contract bug",
    },
    {
        "name": "اقتصاد کلان",
        "name_fa": "اقتصاد کلان",
        "description": "نرخ بهره، تورم، فدرال رزرو، GDP، اقتصاد جهانی، recession",
    },
    {
        "name": "استیبل‌کوین",
        "name_fa": "استیبل‌کوین",
        "description": "USDT، USDC، DAI، پگ دلاری، stablecoin، ثبات قیمت",
    },
    {
        "name": "صرافی",
        "name_fa": "صرافی",
        "description": "exchange، CEX، DEX، listing، Binance، Coinbase، حجم معاملات",
    },
]

# Top crypto coins — symbol, name
# Embedding text: "{symbol} {name} cryptocurrency blockchain"
DEFAULT_COINS: list[dict] = [
    {"symbol": "BTC",   "name": "Bitcoin"},
    {"symbol": "ETH",   "name": "Ethereum"},
    {"symbol": "BNB",   "name": "BNB"},
    {"symbol": "XRP",   "name": "XRP"},
    {"symbol": "SOL",   "name": "Solana"},
    {"symbol": "ADA",   "name": "Cardano"},
    {"symbol": "DOGE",  "name": "Dogecoin"},
    {"symbol": "AVAX",  "name": "Avalanche"},
    {"symbol": "DOT",   "name": "Polkadot"},
    {"symbol": "MATIC", "name": "Polygon"},
    {"symbol": "LINK",  "name": "Chainlink"},
    {"symbol": "UNI",   "name": "Uniswap"},
    {"symbol": "LTC",   "name": "Litecoin"},
    {"symbol": "BCH",   "name": "Bitcoin Cash"},
    {"symbol": "XLM",   "name": "Stellar"},
    {"symbol": "TRX",   "name": "TRON"},
    {"symbol": "ATOM",  "name": "Cosmos"},
    {"symbol": "SHIB",  "name": "Shiba Inu"},
    {"symbol": "TON",   "name": "Toncoin"},
    {"symbol": "SUI",   "name": "Sui"},
    {"symbol": "APT",   "name": "Aptos"},
    {"symbol": "OP",    "name": "Optimism"},
    {"symbol": "ARB",   "name": "Arbitrum"},
    {"symbol": "FIL",   "name": "Filecoin"},
    {"symbol": "NEAR",  "name": "NEAR Protocol"},
]

# Sample RSS sources — a starter set
DEFAULT_SOURCES: list[dict] = [
    # English
    {"name": "CoinDesk",          "rss_url": "https://www.coindesk.com/arc/outboundfeeds/rss/",       "site_url": "https://www.coindesk.com",         "language": "en", "priority": 9},
    {"name": "CoinTelegraph",     "rss_url": "https://cointelegraph.com/rss",                          "site_url": "https://cointelegraph.com",         "language": "en", "priority": 9},
    {"name": "The Block",         "rss_url": "https://www.theblock.co/rss.xml",                        "site_url": "https://www.theblock.co",           "language": "en", "priority": 8},
    {"name": "Decrypt",           "rss_url": "https://decrypt.co/feed",                                "site_url": "https://decrypt.co",               "language": "en", "priority": 7},
    {"name": "Bitcoin Magazine",  "rss_url": "https://bitcoinmagazine.com/.rss/full/",                 "site_url": "https://bitcoinmagazine.com",       "language": "en", "priority": 7},
    # Persian
    {"name": "ارز دیجیتال",       "rss_url": "https://arzdigital.com/feed/",                           "site_url": "https://arzdigital.com",            "language": "fa", "priority": 9},
    {"name": "میهن بلاکچین",      "rss_url": "https://mihanblockchain.com/feed/",                      "site_url": "https://mihanblockchain.com",       "language": "fa", "priority": 8},
    {"name": "رمزارز",            "rss_url": "https://ramzarz.news/feed/",                             "site_url": "https://ramzarz.news",              "language": "fa", "priority": 7},
]


# ── Seed functions ───────────────────────────────────────────────────────────

async def seed_categories(session) -> int:
    from app.models.category import Category

    inserted = 0
    for row in DEFAULT_CATEGORIES:
        exists = await session.scalar(
            select(Category).where(Category.name == row["name"])
        )
        if not exists:
            session.add(Category(**row))
            inserted += 1
    await session.commit()
    return inserted


async def seed_coins(session) -> int:
    from app.models.coin import Coin

    inserted = 0
    for row in DEFAULT_COINS:
        exists = await session.scalar(
            select(Coin).where(Coin.symbol == row["symbol"])
        )
        if not exists:
            session.add(Coin(**row))
            inserted += 1
    await session.commit()
    return inserted


async def seed_sources(session) -> int:
    from app.models.source import Source

    inserted = 0
    for row in DEFAULT_SOURCES:
        exists = await session.scalar(
            select(Source).where(Source.rss_url == row["rss_url"])
        )
        if not exists:
            session.add(Source(**row))
            inserted += 1
    await session.commit()
    return inserted


async def generate_embeddings(session) -> None:
    """
    Generate and store embeddings for all categories and coins that lack one.
    Requires OPENROUTER_API_KEY to be set.
    """
    from app.core.embeddings import embedding_cache
    from app.models.category import Category
    from app.models.coin import Coin

    # Categories — embed the description (richer semantic signal)
    cats = list(await session.scalars(
        select(Category).where(Category.embedding.is_(None))
    ))
    for cat in cats:
        embed_text = f"{cat.name_fa} {cat.name} {cat.description}"
        cat.embedding = await embedding_cache.embed(embed_text)
        print(f"  ✓ category: {cat.name}")
    await session.commit()

    # Coins — embed "{SYMBOL} {Name} cryptocurrency blockchain"
    coins = list(await session.scalars(
        select(Coin).where(Coin.embedding.is_(None))
    ))
    for coin in coins:
        from app.modules.coins.embed_text import coin_embed_text
        embed_text = coin_embed_text(coin.symbol, coin.name, coin.aliases)
        coin.embedding = await embedding_cache.embed(embed_text)
        print(f"  ✓ coin: {coin.symbol}")
    await session.commit()


# ── Main ─────────────────────────────────────────────────────────────────────

async def main(with_embeddings: bool = False) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        print("Seeding categories…")
        n = await seed_categories(session)
        print(f"  {n} inserted")

        print("Seeding coins…")
        n = await seed_coins(session)
        print(f"  {n} inserted")

        print("Seeding sources…")
        n = await seed_sources(session)
        print(f"  {n} inserted")

        if with_embeddings:
            print("Generating embeddings…")
            await generate_embeddings(session)
        else:
            print(
                "\nSkipped embeddings. "
                "Run with --embeddings to generate them (requires OPENROUTER_API_KEY)."
            )

    print("\nDone.")


if __name__ == "__main__":
    with_embeddings = "--embeddings" in sys.argv
    asyncio.run(main(with_embeddings))
