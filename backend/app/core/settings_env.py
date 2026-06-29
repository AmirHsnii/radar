"""
Raw env-var settings — only used before the DB is available (startup, migrations).
All runtime configuration comes from app.config (DB-backed).
"""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.environ["DATABASE_URL"]
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
WP_URL: str = os.getenv("WP_URL", "")
WP_USERNAME: str = os.getenv("WP_USERNAME", "")
WP_APP_PASSWORD: str = os.getenv("WP_APP_PASSWORD", "")
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")
