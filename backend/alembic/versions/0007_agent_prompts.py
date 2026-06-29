"""seed agent prompts and beat tick setting

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-13
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text("""
        INSERT INTO app_settings (key, value, value_type, description) VALUES
        ('crawler.beat_tick_minutes',       '1', 'int',  'فاصله بررسی Celery Beat برای منابع سررسید (دقیقه)'),
        ('agent.translator.prompt',         '',  'text', 'پرامپت سیستم ترجمه‌کننده — خالی = پیش‌فرض'),
        ('agent.summarizer.prompt',         '',  'text', 'پرامپت سیستم خلاصه‌ساز — خالی = پیش‌فرض'),
        ('agent.sentiment.prompt',          '',  'text', 'پرامپت سیستم آنالیز احساسات — خالی = پیش‌فرض'),
        ('agent.router.prompt',             '',  'text', 'پرامپت تشخیص زبان (Router) — خالی = پیش‌فرض')
        ON CONFLICT (key) DO NOTHING
        """)
    )


def downgrade() -> None:
    op.execute(
        text("""
        DELETE FROM app_settings WHERE key IN (
            'crawler.beat_tick_minutes',
            'agent.translator.prompt',
            'agent.summarizer.prompt',
            'agent.sentiment.prompt',
            'agent.router.prompt'
        )
        """)
    )
