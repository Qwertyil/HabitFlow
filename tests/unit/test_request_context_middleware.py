from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.application import create_app
from src.config import Settings
from src.logging_config import get_request_id
from src.middleware.request_context import register_request_context_middleware
from tests.helpers import async_test_client


def _settings(**overrides: object) -> Settings:
    return Settings(
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT=5432,
        POSTGRES_USER="habitflow",
        POSTGRES_PASSWORD="secret",
        POSTGRES_DB="habitflow",
        REDIS_HOST="127.0.0.1",
        REDIS_PORT=6379,
        REDIS_PASSWORD="redis-secret",
        REDIS_DB=0,
        ZENQUOTES_API_URL="https://example.test/api/quotes",
        REFILL_INTERVAL_HOURS=6,
        DEBUG=False,
        TESTING=False,
        API_DOCS_ENABLED=False,
        UI_SESSION_SECRET_KEY="test-session-secret",
        **overrides,
    )


def _app(*, settings: Settings | None = None) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings or _settings()
    register_request_context_middleware(app)
    return app


@asynccontextmanager
async def _noop_lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    yield


@pytest.mark.asyncio
async def test_middleware_preserves_incoming_request_id_and_sets_response_header(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(settings=_settings(REQUEST_ID_HEADER="X-Correlation-ID"))

    @app.get("/items/{item_id}")
    async def get_item(item_id: str, request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "item_id": item_id,
                "request_id": request.state.request_id,
                "context_request_id": get_request_id(),
            }
        )

    caplog.set_level(logging.INFO, logger="src.middleware.request_context")

    async with async_test_client(app) as client:
        response = await client.get(
            "/items/123?unused=yes",
            headers={"X-Correlation-ID": "req-abc"},
        )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "req-abc"
    assert response.json()["request_id"] == "req-abc"
    assert response.json()["context_request_id"] == "req-abc"

    records = [
        record
        for record in caplog.records
        if record.name == "src.middleware.request_context"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.event == "http_request_completed"
    assert record.method == "GET"
    assert record.path == "/items/{item_id}"
    assert record.status_code == 200
    assert record.client_ip == "127.0.0.1"
    assert record.request_id == "req-abc"
    assert cast(float, record.duration_ms) >= 0


@pytest.mark.asyncio
async def test_middleware_generates_request_id_when_missing() -> None:
    app = _app()

    @app.get("/ping")
    async def ping(request: Request) -> JSONResponse:
        return JSONResponse({"request_id": request.state.request_id})

    async with async_test_client(app) as client:
        response = await client.get("/ping")

    generated_request_id = response.headers["X-Request-ID"]
    assert response.status_code == 200
    assert response.json()["request_id"] == generated_request_id
    assert UUID(generated_request_id).version == 4
    assert get_request_id() is None


@pytest.mark.asyncio
async def test_successful_healthcheck_logs_at_debug_to_reduce_noise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app()

    @app.get("/healthz/live")
    async def live_health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    caplog.set_level(logging.DEBUG, logger="src.middleware.request_context")

    async with async_test_client(app) as client:
        response = await client.get("/healthz/live")

    assert response.status_code == 200
    records = [
        record
        for record in caplog.records
        if record.name == "src.middleware.request_context"
    ]
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert records[0].path == "/healthz/live"


def test_create_app_registers_request_context_outside_security_headers() -> None:
    app = create_app(settings=_settings())

    middleware_dispatch_names = [
        middleware.kwargs["dispatch"].__name__
        for middleware in app.user_middleware
        if "dispatch" in middleware.kwargs
    ]
    request_context_index = middleware_dispatch_names.index("add_request_context")
    security_headers_index = middleware_dispatch_names.index("add_security_headers")

    assert request_context_index < security_headers_index


@pytest.mark.asyncio
async def test_create_app_preserves_request_id_through_full_middleware_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.application.lifespan", _noop_lifespan)
    app = create_app(settings=_settings(REQUEST_ID_HEADER="X-Correlation-ID"))

    async with async_test_client(app) as client:
        response = await client.get(
            "/healthz/live",
            headers={"X-Correlation-ID": "req-create-app"},
        )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "req-create-app"


@pytest.mark.asyncio
async def test_unhandled_exception_response_keeps_request_id_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.application.lifespan", _noop_lifespan)
    app = create_app(settings=_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/boom")

    assert response.status_code == 500
    assert response.headers["X-Request-ID"]
    assert UUID(response.headers["X-Request-ID"]).version == 4


@pytest.mark.asyncio
async def test_unhandled_exception_logs_keep_request_id_context(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("src.application.lifespan", _noop_lifespan)
    app = create_app(settings=_settings(REQUEST_ID_HEADER="X-Correlation-ID"))

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    caplog.set_level(logging.ERROR)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/boom",
                headers={"X-Correlation-ID": "req-error-123"},
            )

    assert response.status_code == 500
    exception_records = [
        record
        for record in caplog.records
        if record.name == "src.exception_handlers"
        and record.getMessage() == "Unhandled error on GET /boom"
    ]
    assert len(exception_records) == 1
    assert exception_records[0].request_id == "req-error-123"


@pytest.mark.asyncio
async def test_unhandled_exception_emits_one_completion_log(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("src.application.lifespan", _noop_lifespan)
    app = create_app(settings=_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("boom")

    caplog.set_level(logging.INFO, logger="src.middleware.request_context")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/boom")

    assert response.status_code == 500
    completion_records = [
        record
        for record in caplog.records
        if record.name == "src.middleware.request_context"
        and record.event == "http_request_completed"
    ]
    assert len(completion_records) == 1
    assert completion_records[0].status_code == 500
    assert completion_records[0].path == "/boom"
