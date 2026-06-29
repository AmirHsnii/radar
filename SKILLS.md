# SKILLS.md — Backend Developer Agent

## Identity & Responsibility

You are a senior Python backend developer working on **Radar**.  
Your job is to implement, debug, and optimize backend services.

---

## Core Skills

### Python & Async
- **Always async/await** — no blocking I/O
- Use `asyncpg` or `sqlalchemy[asyncio]` for the database
- Use `httpx.AsyncClient` for HTTP calls
- Use `asyncio.gather()` for parallelism

```python
# ✅ Correct pattern for concurrent calls
results = await asyncio.gather(
    fetch_content(url1),
    fetch_content(url2),
    return_exceptions=True  # do not propagate errors
)
```

### FastAPI
- All routers live in `app/api/` with a clear prefix
- Response models use Pydantic v2
- Dependency injection for DB session and settings
- Exception handlers in `app/main.py`

```python
# Standard router pattern
router = APIRouter(prefix="/api/sources", tags=["sources"])

@router.get("/", response_model=list[SourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    ...
```

### OpenRouter / OpenAI-compatible
- Always use `app.core.openrouter.OpenRouterClient` (or `get_agent_client` per agent)
- Read models from `settings.get("ai.fast_model")` — never hardcode
- Use `response_format={"type": "json_object"}` for JSON output
- Always parse JSON with try/except

```python
# Standard LLM call pattern
response = await client.chat(
    model=await settings.get("ai.fast_model", "google/gemini-flash-1.5"),
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    response_format={"type": "json_object"},
    max_tokens=await settings.get("ai.summary_max_tokens", 200),
    task_name="summarize",
    news_id=news_id
)

try:
    result = json.loads(response.content)
except json.JSONDecodeError:
    # fallback: extract with regex
    ...
```

### Celery
- Workers start from `celery_worker.py`
- Beat schedule from `celery_beat.py`
- Celery tasks must use `app.core.async_runner.run_async()` — not raw `asyncio.run()` twice per task
- Task retry via `bind=True`, `max_retries`, and `default_retry_delay`

```python
from app.core.async_runner import run_async

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_news_item_task(self, news_id: int) -> bool:
    return run_async(_process_and_finalize(news_id))
```

### Embedding & Vector Search
- `pgvector` extension in PostgreSQL
- Embeddings via `text-embedding-3-small` through OpenRouter
- Redis cache with pickle (TTL configurable via `embedding.cache_ttl_seconds`)
- Cosine similarity with `numpy` in the classifier

```python
# Vector search pattern (pgvector distance operator)
async def find_similar_categories(embedding: list[float]) -> list[Category]:
    query = """
        SELECT *, (embedding <=> $1::vector) as distance
        FROM categories
        WHERE (embedding <=> $1::vector) < $2
        ORDER BY distance
        LIMIT 5
    """
    threshold = 1 - await settings.get("classifier.category_threshold", 0.65)
    return await db.fetch_all(query, embedding, threshold)
```

---

## Code Quality Rules

### Error Handling
```python
# Always catch specific exceptions
try:
    result = await llm_client.chat(...)
except httpx.TimeoutException:
    await dlq.send(news_id, stage="translate", error=e, retry_count=retry_count)
    raise
except json.JSONDecodeError as e:
    logger.warning(f"JSON parse failed for news {news_id}: {e}")
    # fallback strategy
```

### Logging
```python
import structlog
logger = structlog.get_logger(__name__)

# Always add context
logger.info("news_processed",
            news_id=news_id,
            model=model_used,
            cost_usd=cost,
            duration_ms=elapsed)
```

### Database Transactions
```python
async with db.begin():
    await db.execute(insert_news_sql, ...)
    await db.execute(insert_cost_log_sql, ...)
    # if one fails, both roll back
```

### Settings — never hardcode
```python
# ✅
threshold = await settings.get("classifier.coin_threshold", 0.65)
model = await settings.get("ai.fast_model", "google/gemini-flash-1.5")

# ❌
threshold = 0.65
model = "google/gemini-flash-2.5"
```

---

## File Structure

```
backend/app/
├── main.py              # app factory + middleware
├── config.py            # Settings class + SETTING_DEFAULTS
├── core/
│   ├── database.py      # engine + session
│   ├── openrouter.py    # LLM client wrapper
│   ├── embeddings.py    # embedding cache
│   ├── redis_client.py
│   └── async_runner.py  # Celery async entry point
├── models/              # SQLAlchemy ORM models
├── api/                 # FastAPI routers
├── modules/             # business logic (no FastAPI dependency)
│   ├── crawler/
│   ├── dedup/
│   ├── pipeline/
│   ├── publisher/
│   └── cost/
└── tasks/               # Celery tasks
```

---

## Pre-commit Checklist

- [ ] No hardcoded configuration values?
- [ ] All I/O is async?
- [ ] Cost tracking on every LLM call?
- [ ] Errors routed to DLQ?
- [ ] Structured logging with context?
- [ ] Unit tests added or updated?

---

## Key Dependencies

See `backend/requirements.txt` for pinned versions. Core stack:

```txt
fastapi
sqlalchemy[asyncio]
asyncpg
celery[redis]
redis
httpx
openai              # OpenAI-compatible client for OpenRouter
trafilatura
feedparser
pgvector
numpy
structlog
pydantic
alembic
pytest-asyncio
```
