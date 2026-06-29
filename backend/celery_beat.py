"""
Celery Beat — periodic task scheduler entry point.

Run with:
    celery -A celery_beat beat --loglevel=info

The poll interval is read from the database at Beat startup (beat_init signal)
so changing `crawler.poll_interval_minutes` via the settings API takes effect
on the next Beat restart — no code deploy needed.

Fallback: if the DB is unreachable at startup, the default of 15 min is used.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from celery import signals

from app.core.celery_app import celery_app  # noqa: F401 — celery discovery

log = logging.getLogger(__name__)

_DEFAULT_TICK_INTERVAL = 1    # minutes — how often Beat checks due sources
_DEFAULT_DLQ_INTERVAL  = 30  # minutes


async def _read_beat_tick() -> int:
    from app.config import settings
    return int(await settings.get("crawler.beat_tick_minutes", _DEFAULT_TICK_INTERVAL))


def _build_schedule(tick_minutes: int) -> dict:
    return {
        "poll-rss-sources": {
            "task": "tasks.poll_all_sources",
            "schedule": timedelta(minutes=tick_minutes),
        },
        "retry-dlq-items": {
            "task": "tasks.retry_dlq_items",
            "schedule": timedelta(minutes=_DEFAULT_DLQ_INTERVAL),
        },
    }


async def _read_poll_interval() -> int:
    """Backward-compatible alias used in tests."""
    return await _read_beat_tick()


@signals.beat_init.connect
def on_beat_init(sender, **kwargs) -> None:
    """
    Fires once when Beat starts — before the first tick.
    Reads poll interval from DB and applies it to the schedule.
    """
    try:
        tick_minutes = asyncio.run(_read_beat_tick())
    except Exception as exc:
        log.warning(
            "beat_init: could not read beat tick (using %d min default): %s",
            _DEFAULT_TICK_INTERVAL, exc,
        )
        tick_minutes = _DEFAULT_TICK_INTERVAL

    sender.app.conf.beat_schedule = _build_schedule(tick_minutes)
    log.info("beat_init: schedule set, beat_tick=%d min", tick_minutes)


# Static fallback — used when imported without Beat running (tests, imports).
celery_app.conf.beat_schedule = _build_schedule(_DEFAULT_TICK_INTERVAL)
