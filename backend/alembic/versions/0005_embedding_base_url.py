"""add embedding base_url and api_key settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-13
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        text("""
        INSERT INTO app_settings (key, value, value_type, description) VALUES
        ('embedding.base_url', '', 'str',    'Base URL سرویس embedding — خالی = OPENROUTER_BASE_URL'),
        ('embedding.api_key',  '', 'secret', 'API Key سرویس embedding — خالی = OPENROUTER_API_KEY')
        ON CONFLICT (key) DO NOTHING
        """)
    )


def downgrade() -> None:
    op.execute(
        text("""
        DELETE FROM app_settings WHERE key IN ('embedding.base_url', 'embedding.api_key')
        """)
    )
