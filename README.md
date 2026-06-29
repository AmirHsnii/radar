# Radar

Automated crypto news ingestion, AI processing, and WordPress publishing.

Radar discovers articles from RSS feeds, extracts full page content, runs them through a multi-agent AI pipeline (translation, summarization, classification, coin tagging, sentiment), and publishes structured posts to WordPress. An admin panel provides source management, pipeline monitoring, cost tracking, and dead-letter queue handling.

---

## Features

- **RSS crawling** — per-source poll intervals, keyword whitelist for Persian sources, deduplication via Redis
- **Content extraction** — `trafilatura` with `newspaper3k` fallback; graceful `summary_only` mode when fetch fails
- **Multi-agent pipeline** — language routing, EN→FA translation, FA summarization, embedding-based classification
- **Hybrid tagging** — keyword + semantic matching for coins and categories
- **WordPress publisher** — REST API integration with category/tag resolution
- **Cost tracking** — per-call token and USD logging via OpenRouter
- **Dead letter queue** — automatic retries with exponential backoff
- **Admin panel** — React dashboard for sources, news, settings, costs, and DLQ
- **Zero hardcoded config** — all runtime settings live in PostgreSQL (`app_settings`)

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────────┐
│  RSS Feeds  │────▶│ Celery Beat  │────▶│   Crawler   │────▶│  PostgreSQL      │
└─────────────┘     │  + Worker    │     │  + Dedup    │     │  (news, sources) │
                    └──────────────┘     └──────┬──────┘     └──────────────────┘
                                                │
                                                ▼
                    ┌──────────────────────────────────────────────────────────┐
                    │              Multi-Agent AI Pipeline                      │
                    │  Router → Translate/Summarize → Classify → Sentiment      │
                    └──────────────────────────┬───────────────────────────────┘
                                               │
                    ┌──────────────────────────┼───────────────────────────────┐
                    ▼                          ▼                               ▼
            ┌──────────────┐          ┌──────────────┐               ┌──────────────┐
            │  WordPress   │          │ Cost Tracker │               │     DLQ      │
            │  Publisher   │          │   (logs)     │               │   (retry)    │
            └──────────────┘          └──────────────┘               └──────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| API | Python 3.12, FastAPI, SQLAlchemy (async) |
| Task queue | Celery 5.x, Redis |
| Database | PostgreSQL 15 + pgvector |
| AI | OpenRouter (OpenAI-compatible API) |
| Content extraction | trafilatura, newspaper3k, feedparser |
| Frontend | React 18, Vite, Ant Design, TanStack Router |
| Deployment | Docker Compose |

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- An [OpenRouter](https://openrouter.ai/) API key
- A WordPress site with Application Passwords enabled (for publishing)

---

## Quick Start (Docker)

### 1. Clone the repository

```bash
git clone git@github.com:AmirHsnii/radar.git
cd radar
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Your OpenRouter API key |
| `WP_URL` | WordPress site URL |
| `WP_USERNAME` | WordPress username |
| `WP_APP_PASSWORD` | WordPress application password |
| `ADMIN_USERNAME` | Admin panel login |
| `ADMIN_PASSWORD` | Admin panel password |
| `SECRET_KEY` | JWT signing secret (use a strong random value in production) |

> **Note:** Docker Compose overrides `DATABASE_URL` and `REDIS_URL` for internal networking. The values in `.env.example` are for local (non-Docker) development.

### 3. Start the stack

```bash
docker compose up -d --build
```

Migrations run automatically via the `migrate` one-shot service before the backend starts.

### 4. Seed default data

```bash
docker compose exec backend python -m scripts.seed
```

To also generate category and coin embeddings (requires a valid OpenRouter key):

```bash
docker compose exec backend python -m scripts.seed --embeddings
```

### 5. Open the admin panel

| Service | URL |
|---------|-----|
| Admin panel | http://localhost:8101 |
| API (direct) | http://localhost:8100 |
| API health | http://localhost:8100/health |
| API docs | http://localhost:8100/docs |

Log in with the credentials from `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

### 6. Add a news source

1. Go to **Sources** in the admin panel.
2. Add an RSS feed (name, URL, language `en` or `fa`).
3. On creation, the last 5 feed items are bootstrapped and queued for processing.
4. Celery Beat polls active sources on a configurable schedule.

---

## Exposed Ports

| Port | Service |
|------|---------|
| `8101` | Frontend (admin panel) |
| `8100` | FastAPI backend |
| `5435` | PostgreSQL |
| `6381` | Redis |

---

## Local Development (without Docker)

### Backend

```bash
# Start infrastructure only
docker compose up -d postgres redis

# Install dependencies
cd backend
pip install -r requirements.txt

# Run migrations and seed
alembic upgrade head
python -m scripts.seed

# Terminal 1 — API
make dev

# Terminal 2 — Celery worker
make worker

# Terminal 3 — Celery Beat (required for automatic RSS polling)
make beat
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` or use the Vite dev proxy to point at `http://localhost:8000`.

---

## Makefile Commands

```bash
make up              # docker compose up -d
make down            # docker compose down
make logs            # follow all service logs
make build           # rebuild images
make docker-migrate  # run alembic inside backend container
make test            # run pytest
make lint            # ruff check + format check
make seed            # seed DB (local)
make seed-embed      # seed + generate embeddings (local)
```

---

## Pipeline Overview

| Stage | Description |
|-------|-------------|
| **Crawl** | Poll RSS feeds, deduplicate by title hash, apply keyword whitelist |
| **Fetch** | Download article HTML; set `generation_mode=summary_only` on failure |
| **Route** | Detect language; Persian sources skip translation |
| **Translate** | EN articles → Persian title + summary |
| **Summarize** | FA articles → Persian summary |
| **Classify** | Categories (embedding + default fallback), coins (keyword + embedding) |
| **Sentiment** | LLM sentiment — only when coins are detected |
| **Publish** | Push to WordPress (if `publisher.auto_publish` is enabled) |

All settings (models, thresholds, poll intervals, prompts) are stored in `app_settings` and editable from the **Settings** page.

---

## Project Structure

```
radar/
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI routers
│   │   ├── core/             # DB, Redis, OpenRouter, embeddings
│   │   ├── models/           # SQLAlchemy models
│   │   ├── modules/
│   │   │   ├── crawler/      # RSS, content fetch, whitelist
│   │   │   ├── dedup/        # Hash-based deduplication
│   │   │   ├── pipeline/     # AI agents + orchestrator
│   │   │   └── publisher/    # WordPress REST client
│   │   └── tasks/            # Celery tasks
│   ├── alembic/              # Database migrations
│   └── scripts/              # seed, re-embed utilities
├── frontend/                 # React admin panel
├── modules/                  # Detailed module documentation
├── tests/                    # pytest suite
├── docker-compose.yml
├── Makefile
└── .env.example
```

---

## Testing

```bash
# Local
make test

# Inside Docker
docker compose exec backend pytest tests/ -v
```

---

## Documentation

| File | Description |
|------|-------------|
| [PRODUCT_BRIEF.md](PRODUCT_BRIEF.md) | Product goals, phases, and feature spec |
| [AGENTS.md](AGENTS.md) | Multi-agent pipeline specification |
| [CLAUDE.md](CLAUDE.md) | Developer guide and coding conventions |
| [SKILLS.md](SKILLS.md) | Backend agent skill reference |
| [modules/](modules/) | Per-module technical docs (crawler, pipeline, publisher) |

---

## Security

- Never commit `.env` — it is listed in `.gitignore`.
- Rotate `SECRET_KEY`, `ADMIN_PASSWORD`, and API keys in production.
- The admin API requires JWT authentication; all routes except `/api/v1/auth` and `/health` are protected.
- WordPress credentials should use Application Passwords, not the main account password.

---
