from __future__ import annotations

import logging
from types import TracebackType

import httpx
import pytest

from src.config import Settings
from src.jobs.refresh_quotes import refresh_quotes


def _settings(*, testing: bool = False) -> Settings:
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
        TESTING=testing,
        API_DOCS_ENABLED=False,
        UI_SESSION_SECRET_KEY="test-session-secret",
    )


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1


class FakeSessionContext:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> FakeSession:
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        return False


class FakeSessionMaker:
    def __init__(self, session: FakeSession) -> None:
        self._session = session
        self.calls = 0

    def __call__(self) -> FakeSessionContext:
        self.calls += 1
        return FakeSessionContext(self._session)


class FakeQuoteService:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.refresh_calls = 0

    async def refresh_quotes_batch(self) -> None:
        self.refresh_calls += 1
        if self.should_fail:
            raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_refresh_quotes_commits_after_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings = _settings()
    session = FakeSession()
    session_maker = FakeSessionMaker(session)
    quote_service = FakeQuoteService()
    captured_factory_args: dict[str, object] = {}
    http_client = httpx.AsyncClient()

    def fake_build_quote_service(**kwargs: object) -> FakeQuoteService:
        captured_factory_args.update(kwargs)
        return quote_service

    monkeypatch.setattr(
        "src.jobs.refresh_quotes.build_quote_service",
        fake_build_quote_service,
    )
    caplog.set_level(logging.INFO, logger="src.jobs.refresh_quotes")

    try:
        await refresh_quotes(
            settings=settings,
            http_client=http_client,
            session_maker=session_maker,  # type: ignore[arg-type]
        )
    finally:
        await http_client.aclose()

    assert quote_service.refresh_calls == 1
    assert session.commit_calls == 1
    assert session_maker.calls == 1
    assert captured_factory_args["session"] is session
    assert captured_factory_args["http_client"] is http_client
    assert captured_factory_args["settings"] is settings
    assert "Quotes batch refreshed successfully" in caplog.text
    success_records = [
        record
        for record in caplog.records
        if record.name == "src.jobs.refresh_quotes"
        and getattr(record, "event", None) == "quote_refresh_succeeded"
    ]
    assert len(success_records) == 1


@pytest.mark.asyncio
async def test_refresh_quotes_logs_and_skips_commit_after_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession()
    session_maker = FakeSessionMaker(session)
    http_client = httpx.AsyncClient()

    def fake_build_quote_service(**_: object) -> FakeQuoteService:
        return FakeQuoteService(should_fail=True)

    monkeypatch.setattr(
        "src.jobs.refresh_quotes.build_quote_service",
        fake_build_quote_service,
    )
    caplog.set_level(logging.ERROR, logger="src.jobs.refresh_quotes")

    try:
        await refresh_quotes(
            settings=_settings(),
            http_client=http_client,
            session_maker=session_maker,  # type: ignore[arg-type]
        )
    finally:
        await http_client.aclose()

    assert session.commit_calls == 0
    assert session_maker.calls == 1
    assert "Quotes batch refresh failed" in caplog.text
    failure_records = [
        record
        for record in caplog.records
        if record.name == "src.jobs.refresh_quotes"
        and getattr(record, "event", None) == "quote_refresh_failed"
    ]
    assert len(failure_records) == 1


@pytest.mark.asyncio
async def test_refresh_quotes_skips_work_while_running_tests(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = FakeSession()
    session_maker = FakeSessionMaker(session)
    http_client = httpx.AsyncClient()
    build_quote_service_called = False

    def fail_if_called(**_: object) -> FakeQuoteService:
        nonlocal build_quote_service_called
        build_quote_service_called = True
        return FakeQuoteService()

    monkeypatch.setattr(
        "src.jobs.refresh_quotes.build_quote_service",
        fail_if_called,
    )

    caplog.set_level(logging.DEBUG, logger="src.jobs.refresh_quotes")

    try:
        await refresh_quotes(
            settings=_settings(testing=True),
            http_client=http_client,
            session_maker=session_maker,  # type: ignore[arg-type]
        )
    finally:
        await http_client.aclose()

    assert build_quote_service_called is False
    assert session_maker.calls == 0
    assert session.commit_calls == 0
    skip_records = [
        record
        for record in caplog.records
        if record.name == "src.jobs.refresh_quotes"
        and getattr(record, "event", None) == "quote_refresh_skipped_for_tests"
    ]
    assert len(skip_records) == 1
