from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from httpx import AsyncClient

import src.main as main_module
from src.database.connection import get_db
from src.dependencies import (
    get_habit_service,
    get_login_service,
    get_task_service,
    get_theme_service,
    optional_user,
    require_auth,
)
from src.schemas.auth import AuthUser
from src.services import HabitService, TaskService, ThemeService
from tests.api_unit.assertions import assert_json_response, assert_redirect
from tests.helpers import async_test_client, make_auth_user

pytestmark = pytest.mark.asyncio


class _FakeLoginService:
    def __init__(self) -> None:
        self.resolved_user: AuthUser | None = None
        self.resolve_calls: list[str] = []

    async def resolve_user(self, session_id: str) -> AuthUser | None:
        self.resolve_calls.append(session_id)
        return self.resolved_user


@pytest.fixture
async def client() -> AsyncGenerator[tuple[AsyncClient, _FakeLoginService], None]:
    app = FastAPI()
    app.state.settings = main_module.settings
    fake_login_service = _FakeLoginService()

    app.dependency_overrides[get_login_service] = lambda: fake_login_service

    @app.get("/protected-json")
    async def protected_json(current_user: AuthUser = Depends(require_auth)) -> dict[str, str]:
        return {"user_id": str(current_user.id)}

    @app.get("/protected-html", response_class=HTMLResponse)
    async def protected_html(current_user: AuthUser = Depends(require_auth)) -> str:
        return f"hello {current_user.email}"

    @app.get("/optional")
    async def optional(current_user: AuthUser | None = Depends(optional_user)) -> dict[str, bool]:
        return {"authenticated": current_user is not None}

    try:
        async with async_test_client(app) as http_client:
            yield http_client, fake_login_service
    finally:
        app.dependency_overrides.clear()


async def test_require_auth_returns_401_for_api_request_without_cookie(
    client: tuple[AsyncClient, _FakeLoginService],
) -> None:
    http_client, fake_login_service = client

    res = await http_client.get("/protected-json", headers={"Accept": "application/json"})

    assert_json_response(res, status_code=401)
    assert res.json()["detail"] == "Authentication required"
    assert fake_login_service.resolve_calls == []


async def test_require_auth_redirects_html_request_to_login(
    client: tuple[AsyncClient, _FakeLoginService],
) -> None:
    http_client, fake_login_service = client

    res = await http_client.get(
        "/protected-html?foo=bar",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert_redirect(res, location="/auth/login?next=%2Fprotected-html%3Ffoo%3Dbar")
    assert fake_login_service.resolve_calls == []


async def test_optional_user_resolves_user_by_auth_cookie(
    client: tuple[AsyncClient, _FakeLoginService],
) -> None:
    http_client, fake_login_service = client
    fake_login_service.resolved_user = make_auth_user()

    res = await http_client.get(
        "/optional",
        headers={"Cookie": f"{main_module.settings.AUTH_SESSION_COOKIE_NAME}=sess-123"},
    )

    assert_json_response(res, status_code=200)
    assert res.json() == {"authenticated": True}
    assert fake_login_service.resolve_calls == ["sess-123"]


async def test_require_auth_returns_user_when_cookie_session_is_valid(
    client: tuple[AsyncClient, _FakeLoginService],
) -> None:
    http_client, fake_login_service = client
    fake_login_service.resolved_user = make_auth_user()

    res = await http_client.get(
        "/protected-json",
        headers={"Cookie": f"{main_module.settings.AUTH_SESSION_COOKIE_NAME}=sess-valid"},
    )

    assert_json_response(res, status_code=200)
    assert res.json()["user_id"] == str(fake_login_service.resolved_user.id)
    assert fake_login_service.resolve_calls == ["sess-valid"]


async def test_public_service_providers_do_not_require_authentication() -> None:
    app = FastAPI()
    app.state.settings = main_module.settings
    from src.redis import RedisAdapter

    app.state.redis_adapter = RedisAdapter(main_module.settings)

    async def override_get_db(
        request: Request,
    ) -> AsyncGenerator[object, None]:
        yield object()

    app.dependency_overrides[get_db] = override_get_db

    @app.get("/theme-service")
    async def theme_service_route(
        service: ThemeService = Depends(get_theme_service),
    ) -> dict[str, str]:
        return {"service": service.__class__.__name__}

    @app.get("/task-service")
    async def task_service_route(
        service: TaskService = Depends(get_task_service),
    ) -> dict[str, str]:
        return {"service": service.__class__.__name__}

    @app.get("/habit-service")
    async def habit_service_route(
        service: HabitService = Depends(get_habit_service),
    ) -> dict[str, str]:
        return {"service": service.__class__.__name__}

    try:
        async with async_test_client(app) as http_client:
            for path in ("/theme-service", "/task-service", "/habit-service"):
                res = await http_client.get(path, headers={"Accept": "application/json"})
                assert_json_response(res, status_code=200)
    finally:
        app.dependency_overrides.clear()
