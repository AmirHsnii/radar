"""
Normalize collection-root API paths so both /foo and /foo/ work.

FastAPI runs with redirect_slashes=False, so /api/v1/sources and /api/v1/sources/
are different routes. Collection handlers are registered on the trailing-slash form.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Router prefix + route "/" → these paths without trailing slash must be rewritten.
_COLLECTION_ROOTS = frozenset({
    "/api/v1/news",
    "/api/v1/sources",
    "/api/v1/dlq",
    "/api/v1/settings",
})


class ApiTrailingSlashMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in _COLLECTION_ROOTS:
            request.scope["path"] = f"{path}/"
            raw = request.scope.get("raw_path")
            if isinstance(raw, bytes):
                request.scope["raw_path"] = f"{path}/".encode()
        return await call_next(request)
