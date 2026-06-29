"""
PipelineOrchestrator — coordinates the full news processing pipeline.

Flow:
  fetch → route → translate|summarize → classify → persist

BatchProcessor — processes multiple items by batching LLM calls.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import structlog

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.models.news import NewsItem
from app.models.source import Source
from app.modules.crawler.content_resolve import resolve_article_content
from app.models.news import GENERATION_MODE_FULL, GENERATION_MODE_SUMMARY_ONLY
from app.modules.dlq import send_to_dlq
from app.modules.pipeline.classifier import ClassificationResult, classifier_agent
from app.modules.pipeline.classify_text import build_classify_text
from app.modules.pipeline.router import router_agent
from app.modules.pipeline.summarizer import SummaryInput, summary_agent
from app.modules.pipeline.translator import TranslationInput, translation_agent

log = structlog.get_logger(__name__)

_PIPELINE_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Pipeline stage tracking
# ---------------------------------------------------------------------------

@dataclass
class PipelineStageResult:
    stage: str
    status: Literal["ran", "skipped", "failed", "queued"]
    reason: str | None = None
    duration_ms: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PipelineStageTracker:
    def __init__(self) -> None:
        self.stages: list[PipelineStageResult] = []

    def add(
        self,
        stage: str,
        status: Literal["ran", "skipped", "failed", "queued"],
        *,
        reason: str | None = None,
        duration_ms: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        self.stages.append(PipelineStageResult(
            stage=stage,
            status=status,
            reason=reason,
            duration_ms=duration_ms,
            detail=detail or {},
        ))

    def to_json(self) -> str:
        return json.dumps([s.to_dict() for s in self.stages], ensure_ascii=False)


def append_publish_stage(
    stages_json: str | None,
    *,
    status: Literal["ran", "skipped", "failed", "queued"],
    reason: str | None = None,
    detail: dict[str, Any] | None = None,
) -> str:
    stages: list[dict[str, Any]] = []
    if stages_json:
        try:
            stages = json.loads(stages_json)
        except json.JSONDecodeError:
            pass
    stages.append(PipelineStageResult(
        stage="publish",
        status=status,
        reason=reason,
        detail=detail or {},
    ).to_dict())
    return json.dumps(stages, ensure_ascii=False)


# ---------------------------------------------------------------------------
# ProcessedNews — output of the pipeline
# ---------------------------------------------------------------------------

@dataclass
class ProcessedNews:
    news_id: int
    title_fa: str
    summary_fa: str
    categories: list[str]
    category_ids: list[int]
    coins: list[str]
    sentiment: Literal["positive", "negative", "neutral"] | None
    language: str
    processing_cost_usd: float
    models_used: list[str]
    processing_time_ms: int
    pipeline_version: str = _PIPELINE_VERSION
    stages: list[PipelineStageResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PipelineOrchestrator
# ---------------------------------------------------------------------------

class PipelineOrchestrator:
    """
    Runs the full pipeline for a single news item.

    Every stage is timed and logged. Any exception triggers DLQ and re-raises
    so the caller can mark the item as failed.
    """

    async def process(self, item: NewsItem) -> ProcessedNews:
        t0 = time.perf_counter()
        bound = log.bind(news_id=item.id, url=item.url)
        tracker = PipelineStageTracker()

        source_lang = await self._get_source_language(item.source_id)

        # ------------------------------------------------------------------
        # Stage 1: content fetch
        # ------------------------------------------------------------------
        if item.content and item.content.strip():
            t_stage = time.perf_counter()
            item.generation_mode = item.generation_mode or GENERATION_MODE_FULL
            tracker.add(
                "fetch", "skipped",
                reason="content_already_present",
                duration_ms=_ms(t_stage),
                detail={"chars": len(item.content), "generation_mode": item.generation_mode},
            )
            text = item.content.strip()
        else:
            t_stage = time.perf_counter()
            text, item.generation_mode = await resolve_article_content(item)
            item.status = "fetched"
            if item.generation_mode == GENERATION_MODE_SUMMARY_ONLY:
                tracker.add(
                    "fetch", "failed",
                    reason="content_fetch_failed",
                    duration_ms=_ms(t_stage),
                    detail={
                        "generation_mode": item.generation_mode,
                        "fallback": "title_only",
                        "chars": len(text),
                    },
                )
                bound.warning("orchestrator.content_fetch_failed_summary_only")
            else:
                tracker.add(
                    "fetch", "ran",
                    duration_ms=_ms(t_stage),
                    detail={"chars": len(text), "generation_mode": item.generation_mode},
                )
            bound.debug(
                "orchestrator.fetched",
                duration_ms=_ms(t_stage),
                chars=len(text),
                generation_mode=item.generation_mode,
            )

        if not text:
            tracker.add("fetch", "failed", reason="empty_content")
            bound.warning("orchestrator.empty_content")
            raise ValueError("No content or title to process")

        # ------------------------------------------------------------------
        # Stage 2: language detection (logging only; routing uses source lang)
        # ------------------------------------------------------------------
        t_stage = time.perf_counter()
        lang_result = await router_agent.detect(
            title=item.title or "",
            content_preview=text[:300],
        )
        lang = lang_result.language
        item.language = lang
        tracker.add(
            "route", "ran",
            duration_ms=_ms(t_stage),
            detail={
                "detected_language": lang,
                "method": lang_result.method,
                "source_language": source_lang,
            },
        )
        bound.debug("orchestrator.language_detected",
                    language=lang, method=lang_result.method,
                    duration_ms=_ms(t_stage))

        # ------------------------------------------------------------------
        # Stage 3: translate (EN source) or summarise (FA source)
        # ------------------------------------------------------------------
        use_translation = source_lang == "en"
        t_stage = time.perf_counter()
        models_used: list[str] = []

        if use_translation:
            tracker.add("summarize", "skipped", reason="english_source")
            t = await translation_agent.process_single(TranslationInput(
                title=item.title or "",
                content=text,
                news_id=item.id,
            ))
            item.title_fa = t.title_fa
            item.summary_fa = t.summary_fa
            item.status = "translated"
            tracker.add(
                "translate", "ran",
                duration_ms=_ms(t_stage),
                detail={"has_summary": bool(item.summary_fa)},
            )
            bound.debug("orchestrator.translated",
                        duration_ms=_ms(t_stage),
                        has_summary=bool(item.summary_fa))
        else:
            tracker.add("translate", "skipped", reason="persian_source")
            item.title_fa = item.title
            prompt_agent = "summarizer_fa" if source_lang == "fa" else "summarizer"
            s = await summary_agent.process_single(SummaryInput(
                title=item.title or "",
                content=text,
                news_id=item.id,
                prompt_agent=prompt_agent,
            ))
            item.summary_fa = s.summary_fa
            item.status = "summarized"
            tracker.add(
                "summarize", "ran",
                duration_ms=_ms(t_stage),
                detail={"prompt_agent": prompt_agent, "has_summary": bool(item.summary_fa)},
            )
            bound.debug("orchestrator.summarized",
                        duration_ms=_ms(t_stage),
                        has_summary=bool(item.summary_fa))

        # ------------------------------------------------------------------
        # Stage 4: classification (categories + coins + sentiment)
        # ------------------------------------------------------------------
        classify_text = await build_classify_text(
            title_fa=item.title_fa,
            summary_fa=item.summary_fa,
            content=item.content,
            raw_title=item.title,
        )

        t_cat = time.perf_counter()
        categories = await classifier_agent.category_tagger.tag(classify_text)
        tracker.add(
            "classify_categories", "ran",
            duration_ms=_ms(t_cat),
            detail={"count": len(categories), "names": [m.name for m in categories]},
        )

        t_coins = time.perf_counter()
        coins = await classifier_agent.coin_tagger.tag(classify_text)
        tracker.add(
            "classify_coins", "ran",
            duration_ms=_ms(t_coins),
            detail={"count": len(coins), "symbols": coins},
        )

        sentiment = None
        if coins:
            t_sent = time.perf_counter()
            sentiment = await classifier_agent.sentiment_analyzer.analyze(
                classify_text, news_id=item.id,
            )
            tracker.add(
                "sentiment", "ran",
                duration_ms=_ms(t_sent),
                detail={"value": sentiment},
            )
        else:
            tracker.add("sentiment", "skipped", reason="no_coins_detected")

        clf = ClassificationResult(
            categories=categories,
            coins=coins,
            sentiment=sentiment,
        )

        item.sentiment = clf.sentiment
        item.coins_json = json.dumps(clf.coins, ensure_ascii=False)
        item.categories_json = json.dumps(
            [m.name_fa for m in clf.categories], ensure_ascii=False
        )
        item.status = "classified"
        item.processed_at = datetime.now(tz=timezone.utc)
        item.pipeline_stages_json = tracker.to_json()

        bound.debug("orchestrator.classified",
                    coins=clf.coins,
                    categories=[m.name for m in clf.categories],
                    sentiment=clf.sentiment)

        total_ms = _ms(t0)
        bound.info("orchestrator.done", total_ms=total_ms)

        return ProcessedNews(
            news_id=item.id,
            title_fa=item.title_fa or "",
            summary_fa=item.summary_fa or "",
            categories=[m.name_fa for m in clf.categories],
            category_ids=[m.id for m in clf.categories],
            coins=clf.coins,
            sentiment=clf.sentiment,
            language=lang,
            processing_cost_usd=0.0,
            models_used=models_used,
            processing_time_ms=total_ms,
            stages=tracker.stages,
        )

    @staticmethod
    async def _get_source_language(source_id: int | None) -> str:
        if source_id is None:
            return "en"
        async with AsyncSessionLocal() as session:
            source = await session.get(Source, source_id)
        return source.language if source else "en"


# ---------------------------------------------------------------------------
# BatchProcessor
# ---------------------------------------------------------------------------

class BatchProcessor:
    """
    Processes a list of NewsItems by batching LLM translation/summary calls.

    Groups EN items together → one translation batch call.
    Groups FA items together → one summary batch call.
    Classify runs per-item (embeddings are cheap).
    """

    async def process_batch(
        self,
        items: list[NewsItem],
        batch_size: int | None = None,
    ) -> list[ProcessedNews | None]:
        """
        Process items in LLM batches. Returns results in same order as input.
        None entries indicate failed items (already sent to DLQ).
        """
        size = batch_size or int(await settings.get("ai.batch_size", 5))
        results: list[ProcessedNews | None] = []

        for chunk in _chunks(items, size):
            chunk_results = await self._process_chunk(chunk)
            results.extend(chunk_results)

        return results

    async def _process_chunk(
        self, items: list[NewsItem]
    ) -> list[ProcessedNews | None]:
        if not items:
            return []

        await asyncio.gather(*[
            self._fetch_content(item) for item in items
        ])

        lang_tasks = [
            router_agent.detect(
                title=item.title or "",
                content_preview=(item.content or "")[:300],
            )
            for item in items
        ]
        lang_results = await asyncio.gather(*lang_tasks)
        for item, lr in zip(items, lang_results):
            item.language = lr.language

        source_langs = await asyncio.gather(*[
            PipelineOrchestrator._get_source_language(item.source_id)
            for item in items
        ])

        en_items = [(i, item) for i, item in enumerate(items)
                    if source_langs[i] == "en"]
        fa_items = [(i, item) for i, item in enumerate(items)
                    if source_langs[i] != "en"]

        if en_items:
            idxs, news = zip(*en_items)
            translations = await translation_agent.process_batch([
                TranslationInput(
                    title=n.title or "",
                    content=n.content or n.title or "",
                    news_id=n.id,
                ) for n in news
            ])
            for idx, n, t in zip(idxs, news, translations):
                n.title_fa = t.title_fa
                n.summary_fa = t.summary_fa
                n.status = "translated"

        if fa_items:
            idxs, news = zip(*fa_items)
            summaries = await summary_agent.process_batch([
                SummaryInput(
                    title=n.title or "",
                    content=n.content or n.title or "",
                    news_id=n.id,
                    prompt_agent="summarizer_fa" if source_langs[idx] == "fa" else "summarizer",
                )
                for idx, n in zip(idxs, news)
            ])
            for idx, n, s in zip(idxs, news, summaries):
                n.title_fa = n.title
                n.summary_fa = s.summary_fa
                n.status = "summarized"

        classify_texts = await asyncio.gather(*[
            build_classify_text(
                title_fa=item.title_fa,
                summary_fa=item.summary_fa,
                content=item.content,
                raw_title=item.title,
            )
            for item in items
        ])
        classify_tasks = [
            classifier_agent.classify(text, news_id=item.id)
            for item, text in zip(items, classify_texts)
        ]
        clf_results: list[ClassificationResult] = await asyncio.gather(*classify_tasks)

        now = datetime.now(tz=timezone.utc)
        out: list[ProcessedNews | None] = []
        for item, clf in zip(items, clf_results):
            item.sentiment = clf.sentiment
            item.coins_json = json.dumps(clf.coins, ensure_ascii=False)
            item.categories_json = json.dumps(
                [m.name_fa for m in clf.categories], ensure_ascii=False
            )
            item.status = "classified"
            item.processed_at = now
            out.append(ProcessedNews(
                news_id=item.id,
                title_fa=item.title_fa or "",
                summary_fa=item.summary_fa or "",
                categories=[m.name_fa for m in clf.categories],
                category_ids=[m.id for m in clf.categories],
                coins=clf.coins,
                sentiment=clf.sentiment,
                language=item.language or "en",
                processing_cost_usd=0.0,
                models_used=[],
                processing_time_ms=0,
            ))

        return out

    @staticmethod
    async def _fetch_content(item: NewsItem) -> None:
        text, mode = await resolve_article_content(item)
        item.generation_mode = mode
        if mode == GENERATION_MODE_FULL and text:
            item.content = text


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

pipeline = PipelineOrchestrator()
batch_processor = BatchProcessor()


# ---------------------------------------------------------------------------
# Backward-compatible entry point (called by Celery process_task)
# ---------------------------------------------------------------------------

async def process_news_item(news_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        item = await session.get(NewsItem, news_id)
        if not item:
            return False

        try:
            await pipeline.process(item)
            await session.commit()
            return True

        except Exception as exc:
            item.retry_count += 1
            item.status = "failed"
            await session.commit()
            await send_to_dlq(
                item_id=item.id,
                stage="pipeline",
                error=str(exc),
                retry_count=item.retry_count,
            )
            return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms(since: float) -> int:
    return int((time.perf_counter() - since) * 1000)


def _chunks(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]
