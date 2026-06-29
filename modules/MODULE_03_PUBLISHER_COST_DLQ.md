# Module 3 — Publisher, Cost Tracker & DLQ

---

## 3.1 WordPress REST Publisher

### Responsibility

Send processed articles to WordPress via the REST API.

### WordPress payload schema

```python
@dataclass
class WordPressPayload:
    title: str           # Persian title
    content: str         # summary + source link (+ auto-generated notice if summary_only)
    status: str          # "publish" or "draft" (from settings)
    categories: list[int]  # WP category IDs
    tags: list[int]      # WP tag IDs (coins)
    meta: dict           # custom fields
    
# meta includes:
{
    "radar_source_name": "CoinDesk",
    "radar_source_url": "https://coindesk.com",
    "radar_original_url": "https://coindesk.com/news/...",
    "radar_coins": ["BTC", "ETH"],
    "radar_sentiment": "positive",
    "radar_language": "en",
    "radar_cost_usd": "0.0034",
    "radar_generation_mode": "full",
    "radar_processed_at": "2024-01-01T12:00:00Z"
}
```

When `generation_mode` is `summary_only`, the post content includes an auto-generated notice that the full article could not be fetched.

### Publisher class

```python
class WordPressPublisher:
    async def publish(self, news: ProcessedNews) -> PublishResult:
        payload = self._build_payload(news)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{wp_url}/wp-json/wp/v2/posts",
                json=payload,
                auth=(wp_username, wp_app_password),
                timeout=await settings.get("publisher.timeout_seconds", 15)
            )
        
        if response.status_code == 201:
            return PublishResult(success=True, wp_post_id=response.json()["id"])
        else:
            raise PublishError(f"WP returned {response.status_code}")
    
    async def ensure_category(self, name: str) -> int:
        """Find or create a category in WP — result is cached."""
    
    async def ensure_tag(self, name: str) -> int:
        """Find or create a coin tag in WP — result is cached."""
```

### Settings

| Key | Default | Description |
|-----|---------|-------------|
| `publisher.wp_url` | — | WordPress site URL |
| `publisher.batch_size` | 10 | Articles per publish batch |
| `publisher.timeout_seconds` | 15 | HTTP timeout |
| `publisher.post_status` | `publish` | Default post status |
| `publisher.auto_publish` | `false` | Auto-publish after processing |
| `publisher.default_author_id` | 1 | Default author ID |

---

## 3.2 Cost Tracker

### Responsibility

Log and report the cost of every LLM call.

### `cost_logs` table

```sql
CREATE TABLE cost_logs (
    id SERIAL PRIMARY KEY,
    news_id INTEGER REFERENCES news_items(id),
    model VARCHAR(100) NOT NULL,
    task_name VARCHAR(50) NOT NULL,  -- 'translate', 'summarize', 'classify', 'sentiment'
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    cost_usd DECIMAL(10, 8) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_cost_logs_created_at ON cost_logs(created_at);
CREATE INDEX idx_cost_logs_model ON cost_logs(model);
```

### Cost tracker class

```python
class CostTracker:
    # Pricing fetched from OpenRouter API and cached
    # Refreshed every 6 hours
    
    async def log(
        self,
        news_id: int | None,
        model: str,
        tokens_in: int,
        tokens_out: int,
        task_name: str
    ):
        pricing = await self._get_model_pricing(model)
        cost = (tokens_in * pricing.input_per_token + 
                tokens_out * pricing.output_per_token)
        
        await db.insert_cost_log(...)
        
        # Check monthly budget
        await self._check_budget_alert()
    
    async def get_daily_summary(self, date: date) -> DailyCostSummary
    async def get_monthly_summary(self, year: int, month: int) -> MonthlyCostSummary
    async def get_cost_per_news(self, news_id: int) -> float
    
    async def _check_budget_alert(self):
        monthly_total = await self.get_current_month_total()
        budget = await settings.get("cost.monthly_budget_usd", 50)
        threshold = await settings.get("cost.alert_threshold_pct", 80)
        
        if monthly_total > budget * (threshold / 100):
            await alert_service.send(
                f"Monthly cost exceeded {threshold}% of budget"
            )
    
    async def _get_model_pricing(self, model: str) -> ModelPricing:
        """Fetch model pricing from OpenRouter API and cache in Redis."""
        cached = await redis.get(f"pricing:{model}")
        if cached:
            return ModelPricing(**json.loads(cached))
        
        # Fetch from OpenRouter
        response = await httpx.get("https://openrouter.ai/api/v1/models")
        models = response.json()["data"]
        model_info = next(m for m in models if m["id"] == model)
        
        pricing = ModelPricing(
            input_per_token=float(model_info["pricing"]["prompt"]),
            output_per_token=float(model_info["pricing"]["completion"])
        )
        await redis.setex(f"pricing:{model}", 21600, json.dumps(pricing.__dict__))
        return pricing
```

### Dashboard API endpoints

```
GET /api/costs/daily?date=2024-01-15
GET /api/costs/weekly?start=2024-01-08
GET /api/costs/monthly?year=2024&month=1
GET /api/costs/per-news?news_id=123
GET /api/costs/by-model?from=2024-01-01&to=2024-01-31
GET /api/costs/summary  # current month total
```

---

## 3.3 Dead Letter Queue (DLQ)

### Responsibility

Manage articles that failed during pipeline processing.

### `dead_letter_queue` table

```sql
CREATE TABLE dead_letter_queue (
    id SERIAL PRIMARY KEY,
    news_id INTEGER REFERENCES news_items(id),
    stage VARCHAR(50) NOT NULL,  -- 'fetch', 'translate', 'classify', 'publish'
    error_message TEXT NOT NULL,
    error_type VARCHAR(100),     -- 'TimeoutError', 'APIError', etc.
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER NOT NULL,
    next_retry_at TIMESTAMP,
    status VARCHAR(20) DEFAULT 'pending',  -- pending, retrying, resolved, discarded
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

CREATE INDEX idx_dlq_status ON dead_letter_queue(status);
CREATE INDEX idx_dlq_next_retry ON dead_letter_queue(next_retry_at) 
    WHERE status = 'pending';
```

### DLQ manager

```python
class DLQManager:
    async def send(
        self,
        news_id: int,
        stage: str,
        error: Exception,
        current_retry_count: int
    ):
        max_retries = await settings.get("ai.max_retries", 3)
        
        if current_retry_count >= max_retries:
            status = "discarded"
            next_retry = None
        else:
            status = "pending"
            # exponential backoff: 5min, 15min, 45min
            delay = 300 * (3 ** current_retry_count)
            next_retry = datetime.now() + timedelta(seconds=delay)
        
        await db.insert_dlq_entry(
            news_id=news_id,
            stage=stage,
            error_message=str(error),
            error_type=type(error).__name__,
            retry_count=current_retry_count,
            max_retries=max_retries,
            next_retry_at=next_retry,
            status=status
        )
    
    async def get_pending_retries(self) -> list[DLQEntry]:
        """Articles whose retry time has arrived."""
        return await db.fetch_dlq_where(
            status="pending",
            next_retry_at__lte=datetime.now()
        )
    
    async def retry(self, dlq_id: int):
        """Admin manually triggers a retry."""
        entry = await db.get_dlq_entry(dlq_id)
        await process_task.delay(entry.news_id, retry_count=entry.retry_count + 1)
        await db.update_dlq_status(dlq_id, "retrying")
    
    async def discard(self, dlq_id: int, reason: str):
        await db.update_dlq_status(dlq_id, "discarded", reason=reason)
```

### Celery Beat task — auto retry

```python
@celery_app.task
async def retry_dlq_items():
    """Runs every 30 minutes."""
    pending = await dlq_manager.get_pending_retries()
    
    for entry in pending:
        await db.update_dlq_status(entry.id, "retrying")
        process_task.delay(entry.news_id, retry_count=entry.retry_count + 1)
    
    logger.info(f"DLQ: {len(pending)} items queued for retry")
```

Celery tasks use `run_async()` to reset async resources between runs and avoid event-loop errors.

### API endpoints

```
GET  /api/dlq?status=pending&page=1
GET  /api/dlq/{id}
POST /api/dlq/{id}/retry
POST /api/dlq/{id}/discard
POST /api/dlq/retry-all      # retry all pending
GET  /api/dlq/stats          # stats: pending, retrying, resolved, discarded
```

---

## 3.4 Settings manager

### Responsibility

Centralized management of all configuration — nothing is hardcoded in application code.

### `app_settings` table

```sql
CREATE TABLE app_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT NOT NULL,
    value_type VARCHAR(20) NOT NULL,  -- 'string', 'int', 'float', 'bool', 'json'
    description TEXT,
    category VARCHAR(50),  -- 'crawler', 'ai', 'cost', 'publisher'
    updated_at TIMESTAMP DEFAULT NOW(),
    updated_by VARCHAR(50)
);
```

### Settings class

```python
class Settings:
    _cache: dict = {}
    _cache_ttl: int = 60  # seconds
    
    async def get(self, key: str, default=None):
        # Check in-memory cache first, then DB
        if key in self._cache:
            cached_val, cached_at = self._cache[key]
            if time.time() - cached_at < self._cache_ttl:
                return cached_val
        
        row = await db.fetchone("SELECT value, value_type FROM app_settings WHERE key=$1", key)
        if not row:
            return default
        
        value = self._cast(row.value, row.value_type)
        self._cache[key] = (value, time.time())
        return value
    
    async def set(self, key: str, value, updated_by: str = "system"):
        str_value = str(value)
        await db.execute(
            "INSERT INTO app_settings (key, value, ...) VALUES (...) ON CONFLICT (key) DO UPDATE ...",
            key, str_value, updated_by
        )
        self._cache.pop(key, None)  # invalidate cache
```

### API endpoints

```
GET  /api/settings                    # all settings grouped by category
GET  /api/settings/prompt-defaults      # default LLM prompt templates
GET  /api/settings/{category}         # settings for one category
PUT  /api/settings/{key}              # update one setting
POST /api/settings/reset/{key}        # reset to default value
```
