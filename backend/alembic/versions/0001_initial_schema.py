"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy import text

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = text("now()")


def upgrade() -> None:
    # ── Extensions ──────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── sources ─────────────────────────────────────────────────────────────
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("rss_url", sa.String(500), nullable=False),
        sa.Column("site_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="5"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_sources_rss_url", "sources", ["rss_url"], unique=True)
    op.create_index("ix_sources_is_active", "sources", ["is_active"])

    # ── news_items ───────────────────────────────────────────────────────────
    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("url", sa.String(1000), nullable=False),
        sa.Column("url_hash", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("title_hash", sa.String(64)),
        sa.Column("content", sa.Text),
        sa.Column("language", sa.String(10)),
        sa.Column("source_id", sa.Integer, sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        # AI outputs
        sa.Column("title_fa", sa.String(500)),
        sa.Column("summary_fa", sa.Text),
        sa.Column("sentiment", sa.String(20)),
        sa.Column("coins_json", sa.Text),
        sa.Column("categories_json", sa.Text),
        sa.Column("wp_post_id", sa.Integer),
        sa.Column("processing_cost_usd", sa.Float),
    )
    op.create_index("ix_news_url_hash", "news_items", ["url_hash"], unique=True)
    op.create_index("ix_news_title_hash", "news_items", ["title_hash"])
    op.create_index("ix_news_status", "news_items", ["status"])
    op.create_index("ix_news_created_at", "news_items", ["created_at"])
    op.create_index("ix_news_source_id", "news_items", ["source_id"])
    op.create_index("ix_news_language", "news_items", ["language"])
    # composite index for the most common query: list by status ordered by date
    op.create_index("ix_news_status_created", "news_items", ["status", "created_at"])

    # ── app_settings ─────────────────────────────────────────────────────────
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("value_type", sa.String(20), nullable=False, server_default="str"),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )

    # ── cost_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "cost_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("news_id", sa.Integer, sa.ForeignKey("news_items.id", ondelete="SET NULL")),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("tokens_in", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("task_name", sa.String(100), nullable=False, server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_cost_logs_news_id", "cost_logs", ["news_id"])
    op.create_index("ix_cost_logs_created_at", "cost_logs", ["created_at"])
    op.create_index("ix_cost_logs_model", "cost_logs", ["model"])

    # ── dead_letter_queue ────────────────────────────────────────────────────
    op.create_table(
        "dead_letter_queue",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("news_id", sa.Integer, sa.ForeignKey("news_items.id", ondelete="SET NULL")),
        sa.Column("stage", sa.String(100), nullable=False),
        sa.Column("error_message", sa.Text, nullable=False),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_dlq_status", "dead_letter_queue", ["status"])
    op.create_index("ix_dlq_next_retry_at", "dead_letter_queue", ["next_retry_at"])
    op.create_index("ix_dlq_news_id", "dead_letter_queue", ["news_id"])

    # ── coins ────────────────────────────────────────────────────────────────
    op.create_table(
        "coins",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("embedding", Vector(1536)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_coins_symbol", "coins", ["symbol"], unique=True)
    # HNSW index for fast cosine similarity search (no training data required at creation)
    op.execute(
        "CREATE INDEX ix_coins_embedding_hnsw ON coins "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # ── categories ───────────────────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("name_fa", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("embedding", Vector(1536)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_NOW),
    )
    op.create_index("ix_categories_name", "categories", ["name"], unique=True)
    op.execute(
        "CREATE INDEX ix_categories_embedding_hnsw ON categories "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    # ── Seed: app_settings ───────────────────────────────────────────────────
    # All values from PRODUCT_BRIEF.md §5 — nothing hardcoded in code
    op.execute(text("""
        INSERT INTO app_settings (key, value, value_type, description) VALUES
        -- Crawler
        ('crawler.poll_interval_minutes',   '15',    'int',   'RSS polling interval in minutes'),
        ('crawler.request_timeout_seconds', '10',    'int',   'HTTP timeout for content fetch (seconds)'),
        ('crawler.max_content_length',      '5000',  'int',   'Max characters of article content to process'),
        -- Dedup
        ('dedup.window_hours',              '24',    'int',   'Dedup time window in hours'),
        ('dedup.method',                    'hash',  'str',   'Dedup method: hash | fuzzy'),
        -- AI models
        ('ai.fast_model',                   'google/gemini-flash-1.5', 'str', 'Cheap model for translation, summary, sentiment'),
        ('ai.quality_model',                'openai/gpt-4o-mini',      'str', 'Better model for retries and difficult content'),
        ('ai.batch_size',                   '5',     'int',   'News items per LLM batch call'),
        ('ai.max_retries',                  '3',     'int',   'Max LLM call retries on error'),
        ('ai.timeout_seconds',              '30',    'int',   'LLM request timeout (seconds)'),
        ('ai.summary_max_tokens',           '150',   'int',   'Max tokens for summary output'),
        ('ai.translation_max_tokens',       '2000',  'int',   'Max tokens for translation output'),
        -- Cost
        ('cost.monthly_budget_usd',         '50',    'float', 'Monthly LLM spend budget in USD'),
        ('cost.alert_threshold_pct',        '80',    'int',   'Alert when monthly spend exceeds this % of budget'),
        -- Publisher
        ('publisher.auto_publish',          'false', 'bool',  'Auto-publish to WordPress after pipeline completes'),
        ('publisher.wp_batch_size',         '10',    'int',   'WordPress posts per publish batch'),
        -- Classifier
        ('classifier.category_threshold',   '0.72',  'float', 'Min cosine similarity to assign a category'),
        ('classifier.coin_threshold',       '0.80',  'float', 'Min cosine similarity to tag a coin')
        ON CONFLICT (key) DO NOTHING
    """))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_categories_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_coins_embedding_hnsw")
    op.drop_table("categories")
    op.drop_table("coins")
    op.drop_table("dead_letter_queue")
    op.drop_table("cost_logs")
    op.drop_table("app_settings")
    op.drop_table("news_items")
    op.drop_table("sources")
    op.execute("DROP EXTENSION IF EXISTS vector")
