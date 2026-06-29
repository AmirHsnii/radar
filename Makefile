.PHONY: dev worker beat migrate test shell lint build up down logs

# ── Local development (without Docker) ──────────────────────────────────────
dev:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd backend && celery -A celery_worker worker --loglevel=info --concurrency=4

beat:
	cd backend && celery -A celery_beat beat --loglevel=info

migrate:
	cd backend && alembic upgrade head

seed:
	cd backend && python -m scripts.seed

seed-embed:
	cd backend && python -m scripts.seed --embeddings

shell:
	cd backend && python -c "import asyncio; from app.core.database import engine; print('DB:', engine.url)"

test:
	cd backend && pytest tests/ -v --tb=short

lint:
	cd backend && ruff check app/ && ruff format --check app/

# ── Docker Compose ────────────────────────────────────────────────────────────
build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

# Run migrations inside the backend container
docker-migrate:
	docker compose exec backend alembic upgrade head

# Open psql shell inside postgres container
psql:
	docker compose exec postgres psql -U radar -d bitpin_radar
