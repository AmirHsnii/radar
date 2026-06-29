"""add per-source poll interval and last_polled_at

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-13
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("poll_interval_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "last_polled_at")
    op.drop_column("sources", "poll_interval_minutes")
