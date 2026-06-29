"""radar six fixes: poll summary, pipeline stages, dual whitelist

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FA_DEFAULTS = (
    '["بیتکوین","اتریوم","ارز دیجیتال","بلاکچین","کریپتو","دیفای",'
    '"توکن","کیف پول","صرافی","رمزارز","رمز ارز","ارزهای دیجیتال"]'
)

_SUMMARIZER_FA_PROMPT = """\
تو یک خلاصه‌ساز حرفه‌ای اخبار اقتصادی و کریپتو فارسی هستی.
این خبر از یک منبع خبری فارسی داخلی است.
یک خلاصه روان و مفید ۲ تا ۳ جمله از خبر بنویس.
اصطلاحات تخصصی کریپتو را به انگلیسی نگه دار (Bitcoin, DeFi, NFT و ...).
فقط JSON برگردان.

خروجی:
{"summary_fa": "..."}"""


def upgrade() -> None:
    op.add_column("sources", sa.Column("last_poll_status", sa.String(20), nullable=True))
    op.add_column("sources", sa.Column("last_poll_new_items", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("last_poll_message", sa.String(500), nullable=True))

    op.add_column("news_items", sa.Column("pipeline_stages_json", sa.Text(), nullable=True))

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE app_settings SET key = :new_key "
            "WHERE key = :old_key"
        ),
        {"old_key": "crawler.whitelist_keywords", "new_key": "crawler.whitelist_keywords_fa"},
    )

    def _insert_setting(key: str, val: str, value_type: str, desc: str) -> None:
        conn.execute(
            sa.text(
                "INSERT INTO app_settings (key, value, value_type, description) "
                "SELECT :insert_key, :val, :value_type, :desc "
                "WHERE NOT EXISTS (SELECT 1 FROM app_settings WHERE key = :check_key)"
            ),
            {
                "insert_key": key,
                "check_key": key,
                "val": val,
                "value_type": value_type,
                "desc": desc,
            },
        )

    _insert_setting(
        "crawler.whitelist_keywords_fa",
        _FA_DEFAULTS,
        "json",
        "JSON list of FA whitelist keywords (required for Persian sources)",
    )
    _insert_setting(
        "crawler.whitelist_keywords_en",
        "[]",
        "json",
        "JSON list of EN whitelist keywords (optional; empty = allow all EN)",
    )
    _insert_setting(
        "agent.summarizer_fa.prompt",
        _SUMMARIZER_FA_PROMPT,
        "str",
        "System prompt for Persian-source summarizer (internal FA news)",
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE app_settings SET key = :old_key "
            "WHERE key = :new_key"
        ),
        {"old_key": "crawler.whitelist_keywords", "new_key": "crawler.whitelist_keywords_fa"},
    )
    conn.execute(sa.text("DELETE FROM app_settings WHERE key = :key"), {"key": "crawler.whitelist_keywords_en"})
    conn.execute(sa.text("DELETE FROM app_settings WHERE key = :key"), {"key": "agent.summarizer_fa.prompt"})

    op.drop_column("news_items", "pipeline_stages_json")
    op.drop_column("sources", "last_poll_message")
    op.drop_column("sources", "last_poll_new_items")
    op.drop_column("sources", "last_poll_status")
