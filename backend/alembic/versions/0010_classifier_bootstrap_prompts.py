"""classifier tuning, source bootstrap, summarizer_fa prompt

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-14
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text("""
        INSERT INTO app_settings (key, value, value_type, description) VALUES
        ('classifier.keyword_match_enabled',  'true',  'bool',  'Match coins by symbol/name/alias in text'),
        ('classifier.semantic_enabled',       'true',  'bool',  'Use embedding cosine similarity for coins/categories'),
        ('classifier.max_classify_chars',     '1500',  'int',   'Max characters sent to embedding classifier'),
        ('classifier.content_snippet_chars',  '800',   'int',   'Content excerpt length for classification'),
        ('crawler.bootstrap_on_create_count', '5',     'int',   'Latest feed items to ingest when a source is created'),
        ('agent.summarizer_fa.prompt',        '',      'text',  'پرامپت خلاصه‌ساز فارسی — خالی = پیش‌فرض')
        ON CONFLICT (key) DO NOTHING
        """)
    )
    op.execute(
        text("UPDATE app_settings SET value = '0.65' WHERE key = 'classifier.coin_threshold'")
    )
    op.execute(
        text("UPDATE app_settings SET value = '0.65' WHERE key = 'classifier.category_threshold'")
    )
    op.execute(
        text("UPDATE app_settings SET value = 'اخبار بازار' WHERE key = 'classifier.default_category'")
    )


def downgrade() -> None:
    op.execute(
        text("""
        DELETE FROM app_settings WHERE key IN (
            'classifier.keyword_match_enabled',
            'classifier.semantic_enabled',
            'classifier.max_classify_chars',
            'classifier.content_snippet_chars',
            'crawler.bootstrap_on_create_count',
            'agent.summarizer_fa.prompt'
        )
        """)
    )
    op.execute(
        text("UPDATE app_settings SET value = '0.80' WHERE key = 'classifier.coin_threshold'")
    )
    op.execute(
        text("UPDATE app_settings SET value = '0.72' WHERE key = 'classifier.category_threshold'")
    )
    op.execute(
        text("UPDATE app_settings SET value = 'بازار' WHERE key = 'classifier.default_category'")
    )
