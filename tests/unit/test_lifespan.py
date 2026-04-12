from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI

from src.config import Settings
from src.lifespan import lifespan


def _settings() -> Settings:
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
        DEBUG=True,
        TESTING=False,
        API_DOCS_ENABLED=False,
        UI_SESSION_SECRET_KEY="test-session-secret",
    )


class FakeHttpClient:
    def __init__(self) -> None:
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> FakeHttpClient:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.exited = True


class FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


class FakeRedisAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
async def test_lifespan_bootstraps_only_web_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI(lifespan=lifespan)
    app.state.settings = _settings()

    http_client = FakeHttpClient()
    engine = FakeEngine()
    redis_instances: list[FakeRedisAdapter] = []
    engine_factory_calls: list[tuple[str, bool]] = []
    refresh_called = False

    @asynccontextmanager
    async def fake_http_client_factory() -> AsyncGenerator[FakeHttpClient, None]:
        async with http_client as client:
            yield client

    def fake_engine_factory(url: str, *, echo: bool) -> FakeEngine:
        engine_factory_calls.append((url, echo))
        return engine

    def fake_redis_adapter_factory(settings: Settings) -> FakeRedisAdapter:
        adapter = FakeRedisAdapter(settings)
        redis_instances.append(adapter)
        return adapter

    async def fake_refresh_quotes(**_: object) -> None:
        nonlocal refresh_called
        refresh_called = True

    monkeypatch.setattr("src.lifespan.httpx.AsyncClient", fake_http_client_factory)
    monkeypatch.setattr("src.lifespan.create_async_engine", fake_engine_factory)
    monkeypatch.setattr("src.lifespan.RedisAdapter", fake_redis_adapter_factory)
    monkeypatch.setattr("src.jobs.refresh_quotes.refresh_quotes", fake_refresh_quotes)

    async with app.router.lifespan_context(app):
        assert app.state.http_client is http_client
        assert app.state.db_engine is engine
        assert hasattr(app.state, "async_session_maker")
        assert redis_instances == [app.state.redis_adapter]
        assert not hasattr(app.state, "scheduler")
        assert refresh_called is False

    assert http_client.entered is True
    assert http_client.exited is True
    assert engine_factory_calls == [(app.state.settings.DATABASE_URL_asyncpg, False)]
    assert engine.dispose_calls == 1
    assert redis_instances[0].close_calls == 1
