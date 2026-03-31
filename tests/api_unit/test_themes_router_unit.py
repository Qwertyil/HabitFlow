from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import AsyncClient

from src.csrf import require_csrf
from src.dependencies import (
    get_theme_service,
    get_template_context,
    get_user_theme_service,
    require_auth,
)
from src.main import app
from src.schemas.themes import ThemeCreate, ThemeInDB, ThemeUpdate
from src.utils import PUBLIC_ERRORS, ensure_csrf_token
from tests.api_unit.assertions import (
    assert_html_response,
    assert_json_detail,
    assert_json_response,
    assert_redirect,
)
from tests.helpers import async_test_client, make_auth_user, with_csrf_form

pytestmark = pytest.mark.asyncio


def _mk_theme(name: str, color: str) -> ThemeInDB:
    now = datetime(2026, 1, 1, 0, 0, 0)
    return ThemeInDB(
        id=uuid4(),
        name=name,
        color=color,
        created_at=now,
        updated_at=now,
    )


class _FakeThemeService:
    def __init__(
        self,
        *,
        exists: bool = True,
        create_error: Exception | None = None,
        create_returns_none: bool = False,
        update_error: Exception | None = None,
        update_returns_none: bool = False,
        themes_count: int = 0,
        theme_id: UUID | None = None,
        theme_name: str = "Hobby",
    ):
        self.exists = exists
        self.create_error = create_error
        self.create_returns_none = create_returns_none
        self.update_error = update_error
        self.update_returns_none = update_returns_none
        self.themes_count = themes_count
        self.theme_id = theme_id or uuid4()
        self.theme_name = theme_name

    async def list_themes_with_counts(
        self, page: int = 1, per_page: int = 20
    ) -> tuple[list[ThemeInDB], int]:
        return ([], self.themes_count)

    async def get_existing_colors(self) -> set[str]:
        return set()

    async def create_theme(self, theme_data: ThemeCreate) -> ThemeInDB | None:
        if self.create_error:
            raise self.create_error
        if self.create_returns_none:
            return None
        return _mk_theme(theme_data.name, theme_data.color or "#FF00FF")

    async def get_theme_by_id(self, id: UUID) -> ThemeInDB | None:
        if not self.exists:
            return None
        if id != self.theme_id:
            return None
        now = datetime(2026, 1, 1, 0, 0, 0)
        return ThemeInDB(
            id=self.theme_id,
            name=self.theme_name,
            color="#FF00FF",
            created_at=now,
            updated_at=now,
        )

    async def update_theme(
        self,
        old_theme: ThemeInDB,
        theme_data: ThemeUpdate,
    ) -> ThemeInDB | None:
        if self.update_error:
            raise self.update_error
        if self.update_returns_none:
            return None
        dump = theme_data.model_dump(exclude_unset=True)
        return old_theme.model_copy(update=dump)

    async def delete_theme(self, id: UUID) -> bool:
        if not self.exists:
            return False
        return id == self.theme_id


def _override_theme_service(service: _FakeThemeService) -> None:
    app.dependency_overrides[get_theme_service] = lambda: service
    app.dependency_overrides[get_user_theme_service] = lambda: service


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    async def fake_template_context(request: Request) -> dict[str, object]:
        return {
            "request": request,
            "themes": [],
            "stats": {"active_tasks": 0, "total_habits": 0, "success_rate": 0},
            "csrf_token": ensure_csrf_token(request),
        }

    app.dependency_overrides[get_template_context] = fake_template_context
    app.dependency_overrides[require_auth] = lambda: make_auth_user(
        "theme-user@example.com"
    )
    app.dependency_overrides[require_csrf] = lambda: None
    _override_theme_service(_FakeThemeService())
    try:
        async with async_test_client(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


async def test_update_theme_returns_404_when_missing(client: AsyncClient) -> None:
    _override_theme_service(_FakeThemeService(exists=False))

    res = await client.put(f"/themes/{uuid4()}", json={"name": "X"})

    assert_json_response(res, status_code=404)


async def test_update_theme_returns_success_payload(client: AsyncClient) -> None:
    theme_id = uuid4()
    _override_theme_service(_FakeThemeService(theme_id=theme_id, theme_name="Hobby"))

    res = await client.put(f"/themes/{theme_id}", json={"color": "#FFFFFF"})

    assert_json_response(res, status_code=200)
    data = res.json()
    assert data["status"] == "success"
    assert data["theme"]["name"] == "Hobby"
    assert data["theme"]["color"] == "#FFFFFF"


@pytest.mark.parametrize(
    ("service_kwargs", "expected_status", "expected_detail"),
    [
        (
            {"update_error": ValueError("Theme with this name already exists")},
            400,
            PUBLIC_ERRORS[400],
        ),
        ({"update_returns_none": True}, 500, PUBLIC_ERRORS[500]),
    ],
)
async def test_update_theme_returns_expected_json_error(
    client: AsyncClient,
    service_kwargs: dict[str, object],
    expected_status: int,
    expected_detail: str,
) -> None:
    theme_id = uuid4()
    _override_theme_service(_FakeThemeService(theme_id=theme_id, **service_kwargs))

    res = await client.put(f"/themes/{theme_id}", json={"color": "#FFFFFF"})

    assert_json_detail(res, status_code=expected_status, detail=expected_detail)


async def test_create_theme_returns_redirect_on_success(client: AsyncClient) -> None:
    res = await client.post(
        "/themes/",
        data=await with_csrf_form(client, {"name": "Hobby"}, path="/themes/new"),
        follow_redirects=False,
    )

    assert_redirect(res, location="/themes")


@pytest.mark.parametrize(
    ("service_kwargs", "expected_status", "expected_message"),
    [
        ({"create_error": ValueError("duplicate")}, 400, "duplicate"),
        ({"create_error": RuntimeError("unexpected")}, 500, "unexpected"),
        ({"create_returns_none": True}, 500, "Тема не создана"),
    ],
)
async def test_create_theme_returns_html_error_for_failures(
    client: AsyncClient,
    service_kwargs: dict[str, object],
    expected_status: int,
    expected_message: str,
) -> None:
    _override_theme_service(_FakeThemeService(**service_kwargs))

    res = await client.post(
        "/themes/",
        data=await with_csrf_form(client, {"name": "Hobby"}, path="/themes/new"),
    )

    assert_html_response(res, status_code=expected_status)
    assert expected_message in res.text


async def test_create_theme_rejects_missing_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.post("/themes/", data={"name": "Hobby"})

    assert_html_response(res, status_code=403)
    assert "Сессия формы истекла" in res.text


async def test_create_theme_accepts_valid_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.post(
        "/themes/",
        data=await with_csrf_form(client, {"name": "Hobby"}, path="/themes/new"),
        follow_redirects=False,
    )

    assert_redirect(res, location="/themes")


async def test_get_theme_page_returns_404_when_missing(client: AsyncClient) -> None:
    _override_theme_service(_FakeThemeService(exists=False))

    res = await client.get(f"/themes/{uuid4()}")

    assert_html_response(res, status_code=404)


async def test_update_theme_rejects_missing_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    theme_id = uuid4()
    _override_theme_service(_FakeThemeService(theme_id=theme_id))

    res = await client.put(f"/themes/{theme_id}", json={"color": "#FFFFFF"})

    assert_json_detail(res, status_code=403, detail=PUBLIC_ERRORS[403])


@pytest.mark.parametrize(
    ("themes_count", "query", "expected_location"),
    [
        (0, "/themes/?page=3&per_page=5", "/themes/?per_page=5"),
        (3, "/themes/?page=9&per_page=2", "/themes/?page=2&per_page=2"),
    ],
)
async def test_get_themes_redirects_to_expected_page(
    client: AsyncClient,
    themes_count: int,
    query: str,
    expected_location: str,
) -> None:
    _override_theme_service(_FakeThemeService(themes_count=themes_count))

    res = await client.get(query, follow_redirects=False)

    assert_redirect(res, status_code=302, location=expected_location)
