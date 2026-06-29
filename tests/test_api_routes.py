"""
API route alignment tests — ensure frontend-called paths are not 404.

With redirect_slashes=False, collection roots must accept both /foo and /foo/.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import create_access_token
from app.main import app

_AUTH = {"Authorization": f"Bearer {create_access_token()}"}


def _not_found(resp) -> bool:
    return resp.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/news"),
        ("GET", "/api/v1/news/"),
        ("GET", "/api/v1/sources"),
        ("GET", "/api/v1/sources/"),
        ("POST", "/api/v1/sources"),
        ("POST", "/api/v1/sources/"),
        ("GET", "/api/v1/dlq"),
        ("GET", "/api/v1/dlq/"),
        ("GET", "/api/v1/settings"),
        ("GET", "/api/v1/settings/"),
        ("GET", "/api/v1/costs/daily"),
        ("GET", "/api/v1/costs/monthly"),
        ("GET", "/api/v1/costs/weekly"),
        ("GET", "/api/v1/costs/by-model"),
        ("GET", "/api/v1/costs/summary"),
        ("GET", "/api/v1/dlq/stats"),
        ("POST", "/api/v1/dlq/retry-all"),
        ("GET", "/api/v1/admin/coins"),
        ("GET", "/api/v1/admin/categories"),
        ("GET", "/api/v1/admin/whitelist"),
        ("POST", "/api/v1/admin/coins/re-embed"),
        ("POST", "/api/v1/admin/categories/re-embed"),
        ("POST", "/api/v1/admin/cache/invalidate"),
        ("GET", "/api/v1/news/stats"),
    ],
)
async def test_protected_routes_are_registered(method: str, path: str):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        if method == "GET":
            resp = await client.get(path, headers=_AUTH)
        else:
            resp = await client.post(path, headers=_AUTH, json={})
    assert not _not_found(resp), f"{method} {path} returned 404"


@pytest.mark.asyncio
async def test_auth_login_route_exists():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post("/api/v1/auth/login", json={"username": "x", "password": "y"})
    assert resp.status_code != 404
