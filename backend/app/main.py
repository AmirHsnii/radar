from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api import admin, auth, costs, dlq, news, settings, sources
from app.core.settings_env import DEBUG, LOG_LEVEL
from app.core.trailing_slash import ApiTrailingSlashMiddleware


def _configure_logging() -> None:
    import logging

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if DEBUG:
        # Human-readable in dev
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # JSON in production (parsed by log aggregators)
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processor=renderer,
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()

    # Warm settings cache so first requests don't hit DB
    from app.config import settings as app_settings
    await app_settings.prefetch_all()

    yield


app = FastAPI(
    title="Bitpin Radar API",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(ApiTrailingSlashMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.core.auth import require_admin  # noqa: E402

# Auth router (public — no dependency)
app.include_router(auth.router, prefix="/api/v1")

# Protected routers — all require a valid Bearer token
_protected = {"dependencies": [__import__("fastapi").Depends(require_admin)]}
app.include_router(sources.router, prefix="/api/v1", **_protected)
app.include_router(news.router, prefix="/api/v1", **_protected)
app.include_router(settings.router, prefix="/api/v1", **_protected)
app.include_router(costs.router, prefix="/api/v1", **_protected)
app.include_router(dlq.router, prefix="/api/v1", **_protected)
app.include_router(admin.router, prefix="/api/v1", **_protected)


@app.get("/health")
async def health():
    return {"status": "ok"}
