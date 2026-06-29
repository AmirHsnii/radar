# Radar — Product Brief

**Version:** 1.0.0  
---

## 1. Executive summary

Radar is an automated engine for collecting, processing, and publishing news. It ingests articles from internal (Persian) and external (English) sources, runs intelligent processing, and publishes standardized posts to WordPress.

**Direct competitor:** Tabdeal exchange — Radar product  
**Competitive edge:** Persian domestic source coverage + coin-level sentiment + full cost control

---

## 2. Product goals

| Goal | Success metric |
|------|----------------|
| 24/7 news coverage without manual intervention | uptime > 99% |
| Process 100–500 articles/day | latency < 5 min from discovery to publish |
| Control LLM spend | < $X/month (configurable in dashboard) |
| Translation & summary quality | manual review score > 4/5 |

---

## 3. High-level architecture

```
[RSS Sources] ──► [Crawler & Fetcher] ──► [Dedup Engine] ──► [Task Queue]
                                                                    │
                    [Multi-Agent AI Pipeline] ◄─────────────────────┘
                    ├── Router Agent (fa/en detection)
                    ├── Translation + Summary Agent (EN only)
                    ├── Summary Agent (FA only)
                    └── Classifier + Tagger Agent
                              │
                    [Schema Builder] ──► [WordPress Publisher]
                              │
                    [Cost Tracker] + [Dead Letter Queue] + [Admin Panel]
```

---

## 4. Modules

### Module 1 — Crawler & Content Fetcher
- **RSS discovery**: poll every N minutes (configurable) across all feeds; per-source intervals supported
- **Content extractor**: HTTP fetch to article URL via `trafilatura`, `newspaper3k` as fallback
- **Whitelist filter**: Persian sources require a keyword match; English sources optional (empty list = allow all)
- **Language detection**: rule-based + `langdetect` + LLM fallback in the router
- **Source manager**: name, RSS URL, language (fa/en), active flag, priority, poll interval
- **Bootstrap**: on new source creation, ingest the last N feed items and start processing immediately

### Module 2 — Deduplication engine
- **Method**: SHA-256 hash of normalized title (lowercase, no punctuation, collapsed whitespace)
- **URL dedup**: separate URL hash with Redis TTL
- **Time window**: 24 hours (configurable)
- **Fuzzy matching**: future phase — MinHash or SimHash for content similarity
- **Storage**: Redis with TTL = `dedup.window_hours`

### Module 3 — Multi-agent AI pipeline

**Provider:** OpenRouter (OpenAI-compatible API)  
**Models** (configurable):
- Fast/cheap: `google/gemini-flash-1.5` or `openai/gpt-4o-mini`
- Quality/expensive: `openai/gpt-4o` or `anthropic/claude-3-5-sonnet`

**Agent 1 — Router:** language detection + routing  
**Agent 2A — Translation + Summary (EN):** translate title + 2–3 sentence Persian summary  
**Agent 2B — Summary (FA):** summarize without translation (Persian sources skip translate)  
**Agent 3 — Classifier + Tagger:**
- Categories via embedding cosine similarity + default fallback category
- Coins via keyword match (symbol/name/aliases) + embedding similarity
- Sentiment (positive/negative/neutral) — only when coins are detected

**Cost optimization:**
- Batching: group N articles per LLM call (configurable)
- Cheap model for FA → summary only
- Cheap model for EN → translate + summary
- Quality model for re-processing failed items

### Module 4 — Schema builder & publisher

```json
{
  "title": "Persian article title",
  "content": "One-paragraph summary (HTML)",
  "source_name": "CoinDesk",
  "coins": ["BTC", "ETH"],
  "categories": ["Market", "DeFi"],
  "sentiment": "positive",
  "language": "en",
  "published_at": "2024-01-01T12:00:00Z",
  "processing_cost_usd": 0.0023,
  "generation_mode": "full | summary_only"
}
```

`summary_only` is set when the article page could not be fetched; WordPress posts include an auto-generated notice.

### Module 5 — Cost tracker & monitoring
- Per-article cost (tokens_in × price_in + tokens_out × price_out)
- Daily/weekly/monthly aggregates
- Alert when spend exceeds budget threshold
- Per-model pricing from OpenRouter

### Module 6 — Dead letter queue & retry
- Failed pipeline stages → DLQ
- Automatic retry with exponential backoff (`max_retries` configurable)
- Timeouts → DLQ
- Admin can manually re-process or discard

### Module 7 — Admin panel (React + FastAPI)
- Source management (add/edit/disable/test pipeline)
- Dual whitelist management (FA required, EN optional)
- Coin list management + re-embed
- Category management + re-embed
- **Settings**: all configurable metrics in one place
- **Cost dashboard**: spend charts + per-article cost table
- **DLQ monitor**: error log + retry/discard actions
- **Pipeline monitor**: real-time stage timeline per article

---

## 5. Settings (nothing is hardcoded)

| Key | Default | Description |
|-----|---------|-------------|
| `crawler.poll_interval_minutes` | 15 | Default RSS poll interval |
| `crawler.beat_tick_minutes` | 1 | How often Beat checks due sources |
| `crawler.bootstrap_on_create_count` | 5 | Items to ingest when a source is created |
| `crawler.request_timeout_seconds` | 10 | Content fetch timeout |
| `crawler.max_content_length` | 5000 | Max article characters to process |
| `dedup.window_hours` | 24 | Dedup time window |
| `ai.fast_model` | gemini-flash-1.5 | Fast model |
| `ai.quality_model` | gpt-4o-mini | Quality model |
| `ai.batch_size` | 5 | Articles per batch LLM call |
| `ai.max_retries` | 3 | LLM retry count |
| `classifier.category_threshold` | 0.65 | Cosine threshold for categories |
| `classifier.coin_threshold` | 0.65 | Cosine threshold for coins |
| `classifier.keyword_match_enabled` | true | Symbol/name/alias text matching |
| `classifier.semantic_enabled` | true | Embedding-based matching |
| `pipeline.manual_review_mode` | false | Hold articles for admin approval |
| `publisher.auto_publish` | false | Auto-publish to WordPress |
| `cost.monthly_budget_usd` | 50 | Monthly budget |

---

## 6. Development phases

### Phase 1 — MVP (weeks 1–3)
- [x] Crawler + RSS + content fetcher
- [x] Hash-based dedup
- [x] EN pipeline: translate + summarize + classification
- [x] WordPress publisher
- [x] Base admin panel

### Phase 2 — Full AI (weeks 4–6)
- [x] Multi-agent pipeline
- [x] Embedding-based classification + keyword fallback
- [x] Sentiment analysis
- [x] Cost tracker
- [x] DLQ + retry

### Phase 3 — Quality & scale (weeks 7–10)
- [ ] Fuzzy dedup (MinHash)
- [x] Full FA pipeline (skip translate, dedicated summarizer prompt)
- [ ] A/B testing for models
- [x] Cost dashboard

### Phase 4 — Advanced features
- [ ] Breaking news detection (velocity-based)
- [ ] Entity extraction (people, organizations)
- [ ] Daily/weekly digest
- [ ] Public news API
- [ ] Notifications (Telegram/email) for important stories

---

## 7. Tech stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3.12+ / FastAPI |
| Task queue | Celery 5.x + Redis |
| Database | PostgreSQL 15+ |
| Cache & DLQ | Redis 7+ |
| Vector store | pgvector (inside PostgreSQL) |
| AI provider | OpenRouter (OpenAI-compatible) |
| Content extraction | trafilatura + newspaper3k |
| RSS | feedparser |
| Frontend | React 18 + Ant Design + TanStack Router |
| Deployment | Docker Compose (on-premise) |

---

## 8. Security considerations

- WordPress and OpenRouter API keys in `.env` only (never committed)
- Rate limiting on admin panel
- Log LLM calls without storing full article content where possible
- Automated PostgreSQL backups
