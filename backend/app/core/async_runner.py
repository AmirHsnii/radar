"""Run async coroutines from sync Celery tasks safely.

Each Celery task uses ``asyncio.run()``, which creates and closes an event loop.
Module-level async resources (DB pool, Redis, HTTP clients) must be reset between
runs or the next task hits "Future attached to a different loop".
"""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

T = TypeVar("T")


async def reset_async_resources() -> None:
    """Tear down loop-bound clients before/after each Celery asyncio.run()."""
    try:
        from app.core.database import dispose_async_engine

        await dispose_async_engine()
    except Exception:
        pass

    try:
        from app.core.redis_client import reset_redis

        await reset_redis()
    except Exception:
        pass

    try:
        from app.core.embeddings import reset_embedder_client

        await reset_embedder_client()
    except Exception:
        pass

    try:
        from app.core.openrouter import reset_global_client

        await reset_global_client()
    except Exception:
        pass


async def _run_with_cleanup(coro: Coroutine[object, object, T]) -> T:
    await reset_async_resources()
    try:
        return await coro
    finally:
        await reset_async_resources()


def run_async(coro: Coroutine[object, object, T]) -> T:
    """Single entry point for Celery tasks that need async I/O."""
    return asyncio.run(_run_with_cleanup(coro))
