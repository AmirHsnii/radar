"""
Costs API — LLM spend dashboards.

Endpoints:
  GET /api/costs/daily              → cost summary for a single day
  GET /api/costs/monthly            → cost summary for the current (or given) month
  GET /api/costs/weekly             → cost summary for the last 7 days
  GET /api/costs/by-model           → current-month breakdown grouped by model
  GET /api/costs/summary            → budget alert + daily/monthly totals
  GET /api/costs/per-news/{news_id} → cost logs for a specific news item
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.cost_log import CostLog
from app.modules.cost.tracker import cost_tracker

router = APIRouter(prefix="/costs", tags=["costs"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CostLogOut(BaseModel):
    id: int
    news_id: int | None
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    task_name: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/daily")
async def daily_costs(
    date: str | None = Query(
        None, description="ISO date YYYY-MM-DD (default: today)"
    ),
):
    """Cost summary for a single day."""
    return await cost_tracker.daily(date)


@router.get("/monthly")
async def monthly_costs(
    year: int | None = Query(None, description="Year (default: current year)"),
    month: int | None = Query(None, description="Month 1-12 (default: current month)"),
):
    """Cost summary for a calendar month."""
    if month is not None and not (1 <= month <= 12):
        raise HTTPException(status_code=400, detail="month must be between 1 and 12")
    return await cost_tracker.monthly(year=year, month=month)


@router.get("/weekly")
async def weekly_costs():
    """Cost summary for the last 7 days."""
    return await cost_tracker.weekly()


@router.get("/by-model")
async def costs_by_model():
    """Current-month cost breakdown grouped by model."""
    data = await cost_tracker.monthly()
    return {
        "period": data["period"],
        "by_model": data["by_model"],
    }


@router.get("/summary")
async def costs_summary():
    """Budget alert status plus daily and monthly totals."""
    budget_alert = await cost_tracker.check_budget_alert()
    daily = await cost_tracker.daily()
    monthly = await cost_tracker.monthly()
    return {
        "budget_alert": budget_alert,
        "today": {
            "period": daily["period"],
            "total_cost_usd": daily["total_cost_usd"],
            "calls": daily["calls"],
        },
        "this_month": {
            "period": monthly["period"],
            "total_cost_usd": monthly["total_cost_usd"],
            "calls": monthly["calls"],
        },
    }


@router.get("/per-news/{news_id}", response_model=list[CostLogOut])
async def costs_per_news(news_id: int):
    """All cost log entries for a specific news item."""
    async with AsyncSessionLocal() as session:
        rows = list(await session.scalars(
            select(CostLog)
            .where(CostLog.news_id == news_id)
            .order_by(CostLog.created_at)
        ))
    if not rows:
        # Return empty list rather than 404 — the news item may simply have no costs yet
        return []
    return rows
