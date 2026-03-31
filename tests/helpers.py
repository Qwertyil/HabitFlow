from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette

from src.schemas.auth import AuthUser

_META_CSRF_RE = re.compile(r'<meta name="csrf-token" content="([^"]+)"')
_INPUT_CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def make_auth_user(email: str = "user@example.com") -> AuthUser:
    now = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
    return AuthUser(
        id=uuid4(),
        email=email,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def extract_csrf_token(html: str) -> str:
    for pattern in (_META_CSRF_RE, _INPUT_CSRF_RE):
        match = pattern.search(html)
        if match is not None:
            return match.group(1)
    raise AssertionError("CSRF token not found in HTML response")


async def fetch_csrf_token(client: AsyncClient, path: str = "/") -> str:
    response = await client.get(path)
    assert response.status_code == 200
    return extract_csrf_token(response.text)


async def with_csrf_form(
    client: AsyncClient,
    data: dict[str, object] | None = None,
    *,
    path: str = "/",
) -> dict[str, object]:
    payload = dict(data or {})
    payload["csrf_token"] = await fetch_csrf_token(client, path)
    return payload


async def with_csrf_headers(
    client: AsyncClient,
    headers: dict[str, str] | None = None,
    *,
    path: str = "/",
) -> dict[str, str]:
    request_headers = dict(headers or {})
    request_headers["X-CSRFToken"] = await fetch_csrf_token(client, path)
    return request_headers


@asynccontextmanager
async def async_test_client(
    app: Starlette,
    *,
    base_url: str = "http://test",
) -> AsyncGenerator[AsyncClient, None]:
    """
    httpx.ASGITransport не выполняет lifespan — без этого app.state (db/redis) пустой.
    """
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url=base_url) as client:
            yield client
