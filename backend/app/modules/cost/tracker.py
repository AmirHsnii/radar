"""
CostTracker — records LLM token usage and cost to the DB.

Pricing strategy:
  1. Redis cache (6 h TTL) — per-model pricing fetched from OpenRouter /models
  2. Hardcoded fallback table — if Redis is cold and the API is down
  3. Default: $1 per 1M tokens for unknown models (conservative over-estimate)

All prices are stored in USD per token (NOT per 1M tokens):
  $0.075 / 1M tokens  →  7.5e-8 USD / token
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import func, select

from app.config import settings
from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis
from app.core.settings_env import OPENROUTER_API_KEY, OPENROUTER_BASE_URL
from app.models.cost_log import CostLog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded fallback — USD per token
# ---------------------------------------------------------------------------
_FALLBACK: dict[str, dict[str, float]] = {
    "google/gemini-flash-1.5": {"prompt": 7.5e-8,  "completion": 3.0e-7},
    "google/gemini-pro-1.5":   {"prompt": 1.25e-6, "completion": 5.0e-6},
    "anthropic/claude-3-haiku": {"prompt": 2.5e-7, "completion": 1.25e-6},
    "anthropic/claude-3-sonnet": {"prompt": 3.0e-6, "completion": 1.5e-5},
    "openai/gpt-4o-mini":      {"prompt": 1.5e-7,  "completion": 6.0e-7},
    "openai/gpt-4o":           {"prompt": 2.5e-6,  "completion": 1.0e-5},
}
_DEFAULT_PRICING = {"prompt": 1.0e-6, "completion": 1.0e-6}  # $1/1M fallback

_PRICING_KEY_TPL = "radar:openrouter:pricing:{model}"
_PRICING_ALL_KEY = "radar:openrouter:models_fetched"
_PRICING_TTL = 6 * 3600   # 6 hours


class CostTracker:

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------

    async def get_model_pricing(self, model: str) -> dict[str, float]:
        """
        Returns {"prompt": USD/token, "completion": USD/token}.

        Lookup order:
          1. Redis per-model key  (TTL 6 h)
          2. Fetch all models from OpenRouter + cache all
          3. Hardcoded fallback table
          4. Default $1/1M tokens
        """
        redis = await get_redis()
        key = _PRICING_KEY_TPL.format(model=model)

        cached = await redis.get(key)
        if cached:
            return json.loads(cached)

        # Fetch full model list only once per cache miss (avoid thundering herd)
        all_fetched = await redis.get(_PRICING_ALL_KEY)
        if not all_fetched:
            await self._fetch_and_cache_all(redis)

        # Try again after populate
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)

        # Fall through to hardcoded table
        pricing = _FALLBACK.get(model, _DEFAULT_PRICING)
        log.debug("cost_tracker.pricing_fallback", model=model)
        return pricing

    async def _fetch_and_cache_all(self, redis) -> None:
        """Fetch /models from OpenRouter and cache each model's pricing."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{OPENROUTER_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
                )
                resp.raise_for_status()
                models: list[dict] = resp.json().get("data", [])

            pipe = redis.pipeline()
            for m in models:
                mid = m.get("id", "")
                p = m.get("pricing", {})
                try:
                    pricing = {
                        "prompt":     float(p.get("prompt", 0) or 0),
                        "completion": float(p.get("completion", 0) or 0),
                    }
                except (ValueError, TypeError):
                    continue
                pipe.setex(_PRICING_KEY_TPL.format(model=mid), _PRICING_TTL, json.dumps(pricing))

            # Mark that we've done the bulk fetch so we don't repeat within TTL
            pipe.setex(_PRICING_ALL_KEY, _PRICING_TTL, "1")
            await pipe.execute()

            log.info("cost_tracker.pricing_cached", count=len(models))

        except Exception as exc:
            log.warning("cost_tracker.pricing_fetch_failed", error=str(exc))
            # Mark as attempted so we don't spam the API on every request
            await redis.setex(_PRICING_ALL_KEY, 300, "0")   # retry in 5 min

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    async def log(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        task_name: str = "unknown",
        news_id: int | None = None,
    ) -> None:
        """Compute cost and write a CostLog row."""
        pricing = await self.get_model_pricing(model)
        cost = tokens_in * pricing["prompt"] + tokens_out * pricing["completion"]

        async with AsyncSessionLocal() as session:
            session.add(CostLog(
                news_id=news_id,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                task_name=task_name,
            ))
            await session.commit()

        log.debug(
            "cost_tracker.logged",
            model=model, task=task_name,
            tokens_in=tokens_in, tokens_out=tokens_out,
            cost_usd=round(cost, 8),
        )

    # ------------------------------------------------------------------
    # Budget alert
    # ------------------------------------------------------------------

    async def check_budget_alert(self) -> dict[str, Any]:
        """
        Returns current month spend vs. configured budget.
        `alert` is True when spent_pct >= threshold_pct.
        """
        budget_usd = float(await settings.get("cost.monthly_budget_usd", 50))
        threshold_pct = int(await settings.get("cost.alert_threshold_pct", 80))

        monthly = await self.monthly()
        spent = monthly["total_cost_usd"]
        pct = (spent / budget_usd * 100) if budget_usd > 0 else 0.0

        return {
            "budget_usd": budget_usd,
            "spent_usd": round(spent, 6),
            "spent_pct": round(pct, 1),
            "threshold_pct": threshold_pct,
            "alert": pct >= threshold_pct,
            "period": monthly["period"],
        }

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    async def daily(self, date_str: str | None = None) -> dict[str, Any]:
        """Cost summary for a single day (default: today)."""
        d = date.fromisoformat(date_str) if date_str else date.today()
        start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        end = start + timedelta(days=1)

        return await self._aggregate(
            since=start, until=end,
            period=d.isoformat(),
        )

    async def weekly(self) -> dict[str, Any]:
        """Cost summary for the last 7 days."""
        now = datetime.now(tz=timezone.utc)
        since = now - timedelta(days=7)
        return await self._aggregate(
            since=since, until=now,
            period=f"{since.date().isoformat()} / {now.date().isoformat()}",
        )

    async def monthly(
        self,
        year: int | None = None,
        month: int | None = None,
    ) -> dict[str, Any]:
        """Cost summary for a calendar month (default: current month)."""
        today = date.today()
        y = year or today.year
        m = month or today.month

        start = datetime(y, m, 1, tzinfo=timezone.utc)
        if m == 12:
            end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end = datetime(y, m + 1, 1, tzinfo=timezone.utc)

        return await self._aggregate(
            since=start, until=end,
            period=f"{y:04d}-{m:02d}",
        )

    async def _aggregate(
        self,
        since: datetime,
        until: datetime,
        period: str,
    ) -> dict[str, Any]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    func.coalesce(func.sum(CostLog.cost_usd), 0.0).label("total_cost"),
                    func.coalesce(func.sum(CostLog.tokens_in), 0).label("tokens_in"),
                    func.coalesce(func.sum(CostLog.tokens_out), 0).label("tokens_out"),
                    func.count().label("calls"),
                ).where(
                    CostLog.created_at >= since,
                    CostLog.created_at < until,
                )
            )
            row = result.one()

            # Per-model breakdown
            by_model_rows = await session.execute(
                select(
                    CostLog.model,
                    func.coalesce(func.sum(CostLog.cost_usd), 0.0).label("cost"),
                    func.count().label("calls"),
                ).where(
                    CostLog.created_at >= since,
                    CostLog.created_at < until,
                ).group_by(CostLog.model).order_by(
                    func.sum(CostLog.cost_usd).desc()
                )
            )

        return {
            "period": period,
            "total_cost_usd": float(row.total_cost),
            "tokens_in": int(row.tokens_in),
            "tokens_out": int(row.tokens_out),
            "calls": int(row.calls),
            "by_model": [
                {"model": r.model, "cost_usd": float(r.cost), "calls": int(r.calls)}
                for r in by_model_rows
            ],
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

cost_tracker = CostTracker()
