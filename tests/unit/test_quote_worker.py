from __future__ import annotations

from types import TracebackType

import httpx
import pytest

from src.config import Settings
from src.quote_worker import run_quote_worker, schedule_quote_refresh_job


def _settings(*, interval_hours: int = 6) -> Settings:
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
        REFILL_INTERVAL_HOURS=interval_hours,
        DEBUG=True,
        TESTING=False,
        API_DOCS_ENABLED=False,
        UI_SESSION_SECRET_KEY="test-session-secret",
    )


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []
        self.started = False
        self.shutdown_wait_values: list[bool] = []

    def add_job(self, func: object, **kwargs: object) -> None:
        self.jobs.append({"func": func, **kwargs})

    def start(self) -> None:
        self.started = True

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_wait_values.append(wait)


class FakeHttpClient(httpx.AsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.entered = False
        self.exited = False

    async def __aenter__(self) -> FakeHttpClient:
        self.entered = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exited = True
        await self.aclose()


class FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    async def dispose(self) -> None:
        self.dispose_calls += 1


class FakeStopEvent:
    def __init__(self) -> None:
        self.wait_calls = 0

    async def wait(self) -> None:
        self.wait_calls += 1


def test_schedule_quote_refresh_job_uses_interval_configuration() -> None:
    scheduler = FakeScheduler()
    settings = _settings(interval_hours=0)
    http_client = httpx.AsyncClient()
    session_maker = object()

    async def fake_refresh_job(**_: object) -> None:
        return None

    schedule_quote_refresh_job(
        scheduler,  # type: ignore[arg-type]
        settings=settings,
        http_client=http_client,
        session_maker=session_maker,  # type: ignore[arg-type]
        refresh_job=fake_refresh_job,
    )

    assert len(scheduler.jobs) == 1
    job = scheduler.jobs[0]
    assert job["func"] is fake_refresh_job
    assert job["trigger"] == "interval"
    assert job["hours"] == 12
    assert job["id"] == "refresh_quotes_job"
    assert job["replace_existing"] is True
    assert job["max_instances"] == 1
    assert job["coalesce"] is True
    assert job["kwargs"] == {
        "settings": settings,
        "http_client": http_client,
        "session_maker": session_maker,
    }


@pytest.mark.asyncio
async def test_run_quote_worker_bootstraps_resources_and_shuts_them_down() -> None:
    settings = _settings(interval_hours=3)
    scheduler = FakeScheduler()
    http_client = FakeHttpClient()
    engine = FakeEngine()
    stop_event = FakeStopEvent()
    refresh_calls: list[dict[str, object]] = []
    engine_factory_calls: list[tuple[str, bool]] = []

    def fake_engine_factory(url: str, *, echo: bool) -> FakeEngine:
        engine_factory_calls.append((url, echo))
        return engine

    async def fake_refresh_job(**kwargs: object) -> None:
        refresh_calls.append(kwargs)

    await run_quote_worker(
        settings=settings,
        stop_event=stop_event,  # type: ignore[arg-type]
        scheduler_factory=lambda: scheduler,  # type: ignore[arg-type]
        http_client_factory=lambda: http_client,
        engine_factory=fake_engine_factory,  # type: ignore[arg-type]
        refresh_job=fake_refresh_job,
    )

    assert engine_factory_calls == [(settings.DATABASE_URL_asyncpg, settings.DEBUG)]
    assert http_client.entered is True
    assert http_client.exited is True
    assert scheduler.started is True
    assert scheduler.shutdown_wait_values == [False]
    assert stop_event.wait_calls == 1
    assert engine.dispose_calls == 1
    assert len(scheduler.jobs) == 1
    assert scheduler.jobs[0]["func"] is fake_refresh_job
    assert scheduler.jobs[0]["hours"] == 3
    assert len(refresh_calls) == 1
    assert refresh_calls[0]["settings"] is settings
    assert refresh_calls[0]["http_client"] is http_client
    assert "session_maker" in refresh_calls[0]
