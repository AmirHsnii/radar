"""
ClassifierAgent — categorises, tags coins, and detects sentiment.

Three sub-components that run concurrently:
  • CategoryTagger   — embedding cosine similarity; adds default category on miss
  • CoinTagger       — higher-threshold cosine similarity; max 5 coins
  • SentimentAnalyzer — LLM; only when coins are found

Internal concurrency pattern:
  1. CoinTagger + CategoryTagger start simultaneously as Tasks.
  2. CoinTagger result determines whether SentimentAnalyzer runs.
  3. CategoryTask (already in-flight) + conditional Sentiment gathered together.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Literal

import structlog

from app.config import settings
from app.core.embeddings import cosine_similarity, embedding_cache
from app.core.openrouter import get_agent_client, get_agent_model
from app.modules.pipeline.prompts import get_agent_prompt
from app.modules.pipeline.semantic_match import match_coins_by_keywords, resolve_default_category

log = structlog.get_logger(__name__)

_VALID_SENTIMENTS = frozenset({"positive", "negative", "neutral"})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CategoryMatch:
    id: int
    name: str
    name_fa: str
    score: float


@dataclass
class ClassificationResult:
    categories: list[CategoryMatch] = field(default_factory=list)
    coins: list[str] = field(default_factory=list)
    sentiment: Literal["positive", "negative", "neutral"] | None = None


# ---------------------------------------------------------------------------
# Null coroutine helper
# ---------------------------------------------------------------------------

async def _none() -> None:
    return None


# ---------------------------------------------------------------------------
# CategoryTagger
# ---------------------------------------------------------------------------

class CategoryTagger:
    """Assigns news to matching categories via embedding similarity + default fallback."""

    async def tag(self, text: str) -> list[CategoryMatch]:
        threshold = float(await settings.get("classifier.category_threshold", 0.65))
        default_name = str(await settings.get("classifier.default_category", "اخبار بازار"))
        semantic_on = bool(await settings.get("classifier.semantic_enabled", True))
        max_embed_chars = int(await settings.get("classifier.max_classify_chars", 1500))

        cats = await embedding_cache.get_categories()
        matches: list[CategoryMatch] = []

        if semantic_on and cats:
            embedding = await embedding_cache.embed(text[:max_embed_chars])
            for cat in cats:
                score = cosine_similarity(embedding, cat.vector)
                if score >= threshold:
                    matches.append(CategoryMatch(
                        id=cat.id, name=cat.name, name_fa=cat.name_fa, score=score,
                    ))

        if not matches:
            cat_rows = [(c.id, c.name, c.name_fa) for c in cats]
            resolved = resolve_default_category(cat_rows, default_name)
            if resolved:
                rid, name, name_fa = resolved
                matches.append(CategoryMatch(id=rid, name=name, name_fa=name_fa, score=0.0))
                log.debug("category_tagger.no_match_using_default", default=default_name, resolved=name)
            else:
                log.debug("category_tagger.no_match_no_default", default=default_name)

        return sorted(matches, key=lambda m: m.score, reverse=True)


# ---------------------------------------------------------------------------
# CoinTagger
# ---------------------------------------------------------------------------

class CoinTagger:
    """Tags up to 5 coins via keyword match + embedding cosine similarity."""

    async def tag(self, text: str) -> list[str]:
        threshold = float(await settings.get("classifier.coin_threshold", 0.65))
        keyword_on = bool(await settings.get("classifier.keyword_match_enabled", True))
        semantic_on = bool(await settings.get("classifier.semantic_enabled", True))
        max_embed_chars = int(await settings.get("classifier.max_classify_chars", 1500))

        coins = await embedding_cache.get_coins()
        if not coins:
            return []

        merged: list[str] = []
        seen: set[str] = set()

        def _add(symbol: str) -> None:
            sym = symbol.upper()
            if sym not in seen:
                seen.add(sym)
                merged.append(sym)

        if keyword_on:
            coin_rows = [(c.symbol, c.name, c.aliases) for c in coins]
            for sym in match_coins_by_keywords(text, coin_rows):
                _add(sym)

        if semantic_on:
            embedding = await embedding_cache.embed(text[:max_embed_chars])
            scored: list[tuple[str, float]] = []
            for coin in coins:
                score = cosine_similarity(embedding, coin.vector)
                if score >= threshold:
                    scored.append((coin.symbol, score))
            for sym, _ in sorted(scored, key=lambda x: x[1], reverse=True):
                _add(sym)

        result = merged[:5]
        log.debug(
            "coin_tagger.done",
            matched=len(result),
            keyword=keyword_on,
            semantic=semantic_on,
        )
        return result


# ---------------------------------------------------------------------------
# SentimentAnalyzer
# ---------------------------------------------------------------------------

class SentimentAnalyzer:
    """LLM-based sentiment analysis. Only called when coins are found."""

    async def analyze(self, text: str, news_id: int | None = None) -> str:
        try:
            model = await get_agent_model("sentiment")
            client = await get_agent_client("sentiment")
            system_prompt = await get_agent_prompt("sentiment")
            result = await client.chat(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text[:1000]},
                ],
                max_tokens=30,
                temperature=0.1,
                task_name="sentiment",
                news_id=news_id,
                response_format={"type": "json_object"},
            )
            sentiment = _parse_sentiment(result.content)
        except Exception as exc:
            log.warning("sentiment_analyzer.failed_using_neutral", error=str(exc))
            sentiment = "neutral"

        log.debug("sentiment_analyzer.done", sentiment=sentiment)
        return sentiment


def _parse_sentiment(raw: str) -> str:
    """Extract sentiment value; returns 'neutral' on any failure."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            val = (data.get("sentiment") or "").strip().lower()
            if val in _VALID_SENTIMENTS:
                return val
    except json.JSONDecodeError:
        pass

    # Regex fallback
    m = re.search(r'"sentiment"\s*:\s*"(\w+)"', raw)
    if m:
        val = m.group(1).lower()
        if val in _VALID_SENTIMENTS:
            return val

    log.debug("sentiment_analyzer.invalid_value_defaulting", raw_preview=raw[:80])
    return "neutral"


# ---------------------------------------------------------------------------
# ClassifierAgent
# ---------------------------------------------------------------------------

class ClassifierAgent:
    """
    Orchestrates CategoryTagger, CoinTagger, and SentimentAnalyzer.

    CoinTagger and CategoryTagger start concurrently (as Tasks).
    SentimentAnalyzer runs only if coins are found.
    """

    def __init__(self) -> None:
        self.category_tagger = CategoryTagger()
        self.coin_tagger = CoinTagger()
        self.sentiment_analyzer = SentimentAnalyzer()

    async def classify(
        self,
        text: str,
        news_id: int | None = None,
    ) -> ClassificationResult:
        """
        Classify text into categories, tag coins, and optionally analyse sentiment.

        CoinTagger and CategoryTagger start in parallel as asyncio Tasks.
        After coins are known, SentimentAnalyzer is conditionally gathered with
        the already-running CategoryTagger task.
        """
        # Start both embedding-based taggers immediately — no dependency between them
        cat_task: asyncio.Task[list[CategoryMatch]] = asyncio.ensure_future(
            self.category_tagger.tag(text)
        )
        coin_task: asyncio.Task[list[str]] = asyncio.ensure_future(
            self.coin_tagger.tag(text)
        )

        # Coins needed to decide if sentiment should run
        coins = await coin_task

        # CategoryTagger is already in flight; Sentiment runs only if coins found
        categories, sentiment = await asyncio.gather(
            cat_task,
            self.sentiment_analyzer.analyze(text, news_id=news_id)
            if coins
            else _none(),
        )

        log.debug(
            "classifier_agent.done",
            news_id=news_id,
            categories=[m.name for m in categories],
            coins=coins,
            sentiment=sentiment,
        )

        return ClassificationResult(
            categories=categories,
            coins=coins,
            sentiment=sentiment,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

classifier_agent = ClassifierAgent()


# ---------------------------------------------------------------------------
# Backward-compatible function (used by orchestrator)
# ---------------------------------------------------------------------------

async def classify(text: str, news_id: int | None = None) -> dict:
    """Returns {"coins": [...], "categories": [...], "sentiment": ...}."""
    result = await classifier_agent.classify(text, news_id=news_id)
    return {
        "coins": result.coins,
        "categories": [m.name_fa for m in result.categories],
        "sentiment": result.sentiment,
    }
