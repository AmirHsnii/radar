import redis.asyncio as aioredis

from app.core.settings_env import REDIS_URL

_pool: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _pool


async def reset_redis() -> None:
    """Close the Redis pool — required after each Celery asyncio.run() cycle."""
    global _pool
    if _pool is not None:
        try:
            await _pool.aclose()
        except Exception:
            pass
        _pool = None
