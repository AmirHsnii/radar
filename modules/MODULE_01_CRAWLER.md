# Module 1 — Crawler & Content Fetcher

## Responsibility

Discover new articles from RSS feeds, extract full page content, and apply initial filtering.

## Flow

```
RSS Poll (Celery Beat — per-source due check)
    │
    ▼
feedparser.parse(rss_url)
    │
    ├─► For each new entry:
    │       ├── dedup check (title hash in Redis)
    │       ├── [Persian sources] whitelist keyword filter
    │       └── if passed → persist NewsItem → process_news_item.delay(news_id)
    │
    ▼
Content Fetcher runs later in pipeline (trafilatura → newspaper3k fallback)
    │
    ▼
Task Queue → process_news_item.delay(news_id)
```

**Bootstrap on source create:** when a new source is added, ingest the last N feed items immediately (config: `crawler.bootstrap_on_create_count`, default 5).

## Classes and functions

### `RSSPoller`
```python
class RSSPoller:
    async def poll_all_sources(self) -> list[RawNewsItem]
    async def poll_source(self, source: Source) -> list[RawNewsItem]
    async def _parse_feed(self, url: str) -> list[FeedEntry]
    async def _is_new(self, entry: FeedEntry) -> bool  # dedup check
```

### `ContentFetcher`
```python
class ContentFetcher:
    async def fetch(self, url: str) -> FetchResult
    async def _try_trafilatura(self, url: str) -> str | None
    async def _try_newspaper(self, url: str) -> str | None
    def _clean_text(self, text: str) -> str
```

### `WhitelistFilter`
```python
class WhitelistFilter:
    async def should_include(self, title: str, language: str) -> bool
    async def get_keywords(self, language: str) -> list[str]  # from DB
    def _normalize(self, text: str) -> str
```

Persian sources require a keyword match. English sources are optional — an empty keyword list means allow all.

## Related settings

| Key | Default | Description |
|-----|---------|-------------|
| `crawler.poll_interval_minutes` | 15 | Default interval between polls per source |
| `crawler.beat_tick_minutes` | 1 | How often Beat checks which sources are due |
| `crawler.bootstrap_on_create_count` | 5 | Items to ingest when a source is created |
| `crawler.request_timeout_seconds` | 10 | HTTP timeout |
| `crawler.max_content_length` | 5000 | Max content length to store/process |
| `crawler.max_concurrent_fetches` | 5 | Concurrent fetch limit |
| `crawler.user_agent` | `Radar/1.0` | User-Agent header |
| `crawler.retry_failed_fetch` | `true` | Retry failed page fetches |

## Output data model

```python
@dataclass
class RawNewsItem:
    url: str
    title: str
    title_hash: str        # SHA-256(normalize(title))
    content: str           # full text or empty (filled later in pipeline)
    language: str          # source language: "fa" | "en"
    source_id: int
    published_at: datetime | None
    feed_summary: str | None  # RSS summary if present
```

RSS ingestion stores title and URL only. Full article text is fetched in the pipeline via `content_fetcher`.

## Dedup logic

```python
def compute_title_hash(title: str) -> str:
    normalized = title.lower().strip()
    normalized = re.sub(r'[^\w\s]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()

async def is_duplicate(hash: str, window_hours: int) -> bool:
    key = f"dedup:{hash}"
    exists = await redis.exists(key)
    if not exists:
        await redis.setex(key, window_hours * 3600, "1")
    return bool(exists)
```

## Error handling

- `httpx.TimeoutException` → log + skip (not DLQ — this stage is pre-queue)
- `feedparser` error → log + backoff
- Empty content → send with `content=""` (pipeline handles via `summary_only` mode)
- Inactive source → skip

## Important notes

1. **Source priority:** higher `source.priority` means more frequent polling
2. **User-Agent:** some sites block bots — use a realistic UA string
3. **trafilatura first:** faster and lighter; newspaper3k is the fallback when trafilatura fails
4. **RSS summary:** if the feed already has a good summary, full fetch may be optional — future optimization
5. **Celery Beat:** must be running for automatic polling; without it `last_polled_at` goes stale
