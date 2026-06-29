"""seed wp connection and embedding settings

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-13
"""
from __future__ import annotations

import os
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    wp_url = os.getenv("WP_URL", "")
    wp_username = os.getenv("WP_USERNAME", "")
    wp_app_password = os.getenv("WP_APP_PASSWORD", "")

    conn = op.get_bind()
    conn.execute(
        text("""
        INSERT INTO app_settings (key, value, value_type, description) VALUES
        ('wp.url',                          :wp_url,          'str',    'آدرس سایت WordPress (مثال: https://example.com)'),
        ('wp.username',                     :wp_username,     'str',    'نام کاربری وردپرس'),
        ('wp.app_password',                 :wp_app_password, 'secret', 'Application Password وردپرس'),
        ('wp.request_timeout_seconds',      '30',             'int',    'WordPress HTTP request timeout'),
        ('wp.max_retries',                  '3',              'int',    'WordPress publish retry attempts'),
        ('ai.embedding_model',              'text-embedding-3-small', 'str', 'مدل embedding برای دسته‌بندی و تگ کوین'),
        ('embedding.cache_ttl_seconds',     '3600',           'int',    'Redis TTL for embedding cache entries'),
        ('classifier.default_category',     'بازار',          'str',    'Fallback category when no match found'),
        ('pipeline.manual_review_mode',     'false',          'bool',   'If true, processed news waits for manual approval before publishing'),
        ('crawler.user_agent',              'Mozilla/5.0 (compatible; BitpinRadar/1.0; +https://bitpin.ir)', 'str', 'User-Agent header for HTTP requests'),
        ('crawler.whitelist_keywords',      'null',           'json',   'JSON list of FA whitelist keywords; null = use built-in defaults'),
        ('agent.translator.model',          '',               'str',    'مدل ترجمه‌کننده — خالی = ai.fast_model'),
        ('agent.translator.base_url',       '',               'str',    'Base URL ترجمه‌کننده — خالی = OPENROUTER_BASE_URL'),
        ('agent.translator.api_key',        '',               'secret', 'API Key ترجمه‌کننده — خالی = OPENROUTER_API_KEY'),
        ('agent.summarizer.model',          '',               'str',    'مدل خلاصه‌ساز — خالی = ai.fast_model'),
        ('agent.summarizer.base_url',       '',               'str',    'Base URL خلاصه‌ساز'),
        ('agent.summarizer.api_key',        '',               'secret', 'API Key خلاصه‌ساز'),
        ('agent.sentiment.model',           '',               'str',    'مدل آنالیز احساسات — خالی = ai.fast_model'),
        ('agent.sentiment.base_url',        '',               'str',    'Base URL آنالیز احساسات'),
        ('agent.sentiment.api_key',         '',               'secret', 'API Key آنالیز احساسات')
        ON CONFLICT (key) DO NOTHING
        """),
        {
            "wp_url": wp_url,
            "wp_username": wp_username,
            "wp_app_password": wp_app_password,
        },
    )


def downgrade() -> None:
    op.execute(
        text("""
        DELETE FROM app_settings WHERE key IN (
            'wp.url', 'wp.username', 'wp.app_password',
            'wp.request_timeout_seconds', 'wp.max_retries',
            'ai.embedding_model', 'embedding.cache_ttl_seconds',
            'classifier.default_category', 'pipeline.manual_review_mode',
            'crawler.user_agent', 'crawler.whitelist_keywords',
            'agent.translator.model', 'agent.translator.base_url', 'agent.translator.api_key',
            'agent.summarizer.model', 'agent.summarizer.base_url', 'agent.summarizer.api_key',
            'agent.sentiment.model', 'agent.sentiment.base_url', 'agent.sentiment.api_key'
        )
        """)
    )
