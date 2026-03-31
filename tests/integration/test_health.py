from types import TracebackType

import pytest
from httpx import AsyncClient

from src.database.connection import get_engine
from src.dependencies import get_redis_adapter
from src.main import app
from tests.api_unit.assertions import assert_json_response
from tests.helpers import async_test_client

pytestmark = pytest.mark.asyncio


class _ConnectionStub:
    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail

    async def __aenter__(self) -> "_ConnectionStub":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def execute(self, statement: object) -> int:
        if self.should_fail:
            raise RuntimeError("database is unavailable")
        return 1


class _EngineStub:
    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail

    def connect(self) -> _ConnectionStub:
        return _ConnectionStub(should_fail=self.should_fail)


class _RedisStub:
    def __init__(self, *, should_fail: bool) -> None:
        self.should_fail = should_fail

    async def ping_for_healthcheck(self) -> bool:
        if self.should_fail:
            raise RuntimeError("redis is unavailable")
        return True

    async def ping(self) -> bool:
        raise AssertionError("readiness probe must not use the regular Redis retry path")


class _HealthcheckRedisStub:
    async def ping_for_healthcheck(self) -> bool:
        return False

    async def ping(self) -> bool:
        raise AssertionError("readiness probe must use the dedicated healthcheck ping")


async def test_ready_healthcheck_uses_dedicated_fast_redis_probe() -> None:
    app.dependency_overrides[get_engine] = lambda: _EngineStub(should_fail=False)
    app.dependency_overrides[get_redis_adapter] = lambda: _HealthcheckRedisStub()

    try:
        async with async_test_client(app) as client:
            response = await client.get("/healthz/ready")
    finally:
        app.dependency_overrides.clear()

    assert_json_response(response, status_code=503)
    assert response.json() == {
        "status": "degraded",
        "checks": {
            "postgres": "ok",
            "redis": "error",
        },
    }


async def test_live_healthcheck_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/healthz/live")

    assert_json_response(response, status_code=200)
    assert response.json() == {"status": "ok"}


async def test_ready_healthcheck_returns_ok_when_dependencies_are_available(
    client: AsyncClient,
) -> None:
    response = await client.get("/healthz/ready")

    assert_json_response(response, status_code=200)
    assert response.json() == {
        "status": "ok",
        "checks": {
            "postgres": "ok",
            "redis": "ok",
        },
    }


@pytest.mark.parametrize(
    ("postgres_should_fail", "redis_should_fail", "expected_body"),
    [
        (
            True,
            False,
            {
                "status": "degraded",
                "checks": {
                    "postgres": "error",
                    "redis": "ok",
                },
            },
        ),
        (
            False,
            True,
            {
                "status": "degraded",
                "checks": {
                    "postgres": "ok",
                    "redis": "error",
                },
            },
        ),
        (
            True,
            True,
            {
                "status": "degraded",
                "checks": {
                    "postgres": "error",
                    "redis": "error",
                },
            },
        ),
    ],
)
async def test_ready_healthcheck_returns_503_when_dependency_is_unavailable(
    postgres_should_fail: bool,
    redis_should_fail: bool,
    expected_body: dict[str, object],
) -> None:
    app.dependency_overrides[get_engine] = lambda: _EngineStub(
        should_fail=postgres_should_fail
    )
    app.dependency_overrides[get_redis_adapter] = lambda: _RedisStub(
        should_fail=redis_should_fail
    )

    try:
        async with async_test_client(app) as client:
            response = await client.get("/healthz/ready")
    finally:
        app.dependency_overrides.clear()

    assert_json_response(response, status_code=503)
    assert response.json() == expected_body
