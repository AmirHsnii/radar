"""
Pytest configuration — sets required env vars before any app module is imported.
"""
import os

import pytest

# Must be set before app.core.settings_env is imported during collection.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENROUTER_API_KEY", "sk-test")


@pytest.fixture(autouse=True)
def _reset_whitelist_singleton():
    """Prevent cross-test pollution of the module-level WhitelistFilter cache."""
    from app.modules.crawler.whitelist import whitelist_filter
    whitelist_filter._keywords_fa = None
    whitelist_filter._keywords_en = None
    yield
    whitelist_filter._keywords_fa = None
    whitelist_filter._keywords_en = None
