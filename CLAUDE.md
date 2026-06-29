# CLAUDE.md — Radar

## What is this project?

 Radar is an automated system for collecting, AI-processing, and publishing crypto news.  
Articles are discovered from RSS feeds, content is extracted, processed by a multi-agent AI pipeline, and published to WordPress.

## Project structure

```
radar/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry
│   │   ├── config.py                # Settings from DB — nothing hardcoded
│   │   ├── models/                  # SQLAlchemy models
│   │   │   ├── news.py
│   │   │   ├── source.py
│   │   │   ├── settings.py          # dynamic app_settings table
│   │   │   ├── cost_log.py
│   │   │   └── dlq.py
│   │   ├── modules/
│   │   │   ├── crawler/
│   │   │   │   ├── rss_poller.py    # feedparser polling
│   │   │   │   ├── content_fetcher.py  # trafilatura + newspaper3k
│   │   │   │   ├── source_bootstrap.py # ingest last N items on new source
│   │   │   │   └── whitelist.py     # FA/EN keyword filters
│   │   │   ├── dedup/
│   │   │   │   └── engine.py        # hash-based + Redis TTL
│   │   │   ├── pipeline/
│   │   │   │   ├── router.py        # language detection + routing
│   │   │   │   ├── translator.py    # EN→FA translation agent
│   │   │   │   ├── summarizer.py    # FA summary agent
│   │   │   │   ├── classifier.py    # embedding + keyword classification
│   │   │   │   └── orchestrator.py  # full pipeline orchestration
│   │   │   ├── publisher/
│   │   │   │   └── wordpress.py     # REST API publisher
│   │   │   └── cost/
│   │   │       └── tracker.py       # token counting + cost logging
│   │   ├── tasks/                   # Celery tasks
│   │   │   ├── crawl_task.py
│   │   │   ├── process_task.py
│   │   │   └── publish_task.py
│   │   ├── api/                     # FastAPI routers
│   │   │   ├── sources.py
│   │   │   ├── news.py
│   │   │   ├── settings.py
│   │   │   ├── costs.py
│   │   │   └── dlq.py
│   │   └── core/
│   │       ├── openrouter.py        # OpenAI-compatible client wrapper
│   │       ├── embeddings.py        # embedding helper + cache
│   │       ├── async_runner.py      # safe asyncio for Celery
│   │       └── database.py
│   ├── celery_worker.py
│   ├── celery_beat.py               # scheduler for RSS polling
│   └── requirements.txt
├── frontend/                        # React + Ant Design + TanStack Router
│   ├── src/
│   │   ├── routes/                  # Dashboard, News, Sources, Settings, etc.
│   │   └── components/
│   └── package.json
├── docker-compose.yml
├── .env.example
└── docs/                            # AGENTS.md, PRODUCT_BRIEF.md, etc.
```

## Important coding rules

### 1. No hardcoded values

All settings are read from the `app_settings` table in PostgreSQL.  
Access via: `from app.config import settings; await settings.get("key", default)`

```python
# ✅ correct
poll_interval = await settings.get("crawler.poll_interval_minutes", 15)

# ❌ wrong
poll_interval = 15
```

### 2. OpenRouter client

Always use `app.core.openrouter` — not the raw `openai` SDK directly.  
The wrapper handles retry, cost tracking, and timeouts.

```python
from app.core.openrouter import get_agent_client, get_agent_model

client = await get_agent_client("translator")
model = await get_agent_model("translator")
response = await client.chat(
    model=model,
    messages=[...],
    max_tokens=await settings.get("ai.summary_max_tokens", 150),
    task_name="summarize"  # for cost tracking
)
```

### 3. Cost tracking

Every LLM call must log cost. `OpenRouterClient` does this automatically  
if you call through it. If you call the API directly, invoke `cost_tracker.log()`.

### 4. Error handling & DLQ

Every pipeline exception should go to the DLQ:

```python
from app.modules.dlq import send_to_dlq

try:
    result = await process_news(news_item)
except Exception as e:
    await send_to_dlq(
        item_id=news_item.id,
        stage="translation",
        error=str(e),
        retry_count=news_item.retry_count
    )
```

### 5. Async everywhere

All I/O must be async — no blocking calls.

```python
# ✅ correct
async def fetch_content(url: str) -> str:
    async with httpx.AsyncClient() as client:
        ...

# ❌ wrong
import requests
response = requests.get(url)
```

### 6. Embedding cache

Coin and category embeddings must be cached — do not fetch from the API on every request.  
Use `app.core.embeddings.embedding_cache`, which is Redis-backed.

### 7. Celery + asyncio

Celery tasks are synchronous. Use `run_async()` from `app.core.async_runner` —  
never call `asyncio.run()` more than once per task, and never reuse async clients across loops.

## Environment variables (`.env`)

```
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/radar
REDIS_URL=redis://localhost:6379/0
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
WP_URL=https://your-wordpress.com
WP_USERNAME=...
WP_APP_PASSWORD=...
```

## Database model (summary)

```sql
-- news
news_items(id, url, url_hash, title, title_hash, content, language, source_id,
           status, retry_count, generation_mode, pipeline_stages_json,
           created_at, processed_at)

-- sources
sources(id, name, rss_url, site_url, language, is_active, priority,
        poll_interval_minutes, last_polled_at, ...)

-- dynamic settings
app_settings(key, value, value_type, description, updated_at)

-- cost log
cost_logs(id, news_id, model, tokens_in, tokens_out, cost_usd, task_name, created_at)

-- dead letter queue
dead_letter_queue(id, news_id, stage, error_message, retry_count,
                  max_retries, next_retry_at, status, created_at)

-- coins
coins(id, symbol, name, aliases, embedding vector(1536), updated_at)

-- categories
categories(id, name, name_fa, embedding vector(1536), updated_at)
```

## Celery tasks

- `tasks.poll_all_sources` — every N minutes (beat tick)
- `tasks.bootstrap_source` — on new source creation (last N feed items)
- `tasks.process_news_item` — AI pipeline
- `tasks.publish_to_wordpress` — final publish
- `tasks.retry_dlq_items` — every 30 minutes, retry due DLQ items

## OpenRouter notes

- Base URL: `https://openrouter.ai/api/v1` — OpenAI-compatible
- Model pricing: `https://openrouter.ai/api/v1/models`
- For batching: send multiple items in one call, not N separate calls
- `usage.prompt_tokens` and `usage.completion_tokens` are in the response

## Common commands

```bash
# Development
docker compose up -d postgres redis
uvicorn app.main:app --reload
celery -A celery_worker worker --loglevel=info
celery -A celery_beat beat --loglevel=info

# Migrations
alembic upgrade head

# Tests
pytest tests/ -v
```
