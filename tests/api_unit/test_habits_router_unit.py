from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import date
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import AsyncClient

from src.csrf import require_csrf
from src.dependencies import (
    get_habit_service,
    get_template_context,
    get_user_habit_service,
    require_auth,
)
from src.exceptions import HabitNotFound
from src.main import app
from src.schemas.habits import HabitCompletionResult
from src.utils import ensure_csrf_token
from tests.api_unit.assertions import (
    assert_html_response,
    assert_json_detail,
    assert_json_response,
    assert_redirect,
)
from tests.helpers import async_test_client, make_auth_user, with_csrf_form
from src.utils import PUBLIC_ERRORS

pytestmark = pytest.mark.asyncio


class _FakeHabitService:
    def __init__(
        self,
        *,
        exists: bool = True,
        create_error: Exception | None = None,
        update_error: Exception | None = None,
        update_returns_none: bool = False,
        complete_error: Exception | None = None,
        incomplete_error: Exception | None = None,
        delete_error: Exception | None = None,
    ):
        self.exists = exists
        self.create_error = create_error
        self.update_error = update_error
        self.update_returns_none = update_returns_none
        self.complete_error = complete_error
        self.incomplete_error = incomplete_error
        self.delete_error = delete_error

    async def list_habits(self, *args: object, **kwargs: object) -> tuple[list[object], int]:
        return ([], 0)

    async def create_habit(self, habit_data: object) -> object:
        if self.create_error:
            raise self.create_error
        return {"id": uuid4()}

    async def get_habit(self, habit_id: UUID) -> object | None:
        if not self.exists:
            return None
        return {"id": habit_id}

    async def update_habit(self, habit_id: UUID, habit_data: object) -> object | None:
        if self.update_error:
            raise self.update_error
        if self.update_returns_none:
            return None
        return {"id": habit_id}

    async def complete_habit(self, habit_id: UUID) -> HabitCompletionResult:
        if self.complete_error:
            raise self.complete_error
        if not self.exists:
            raise HabitNotFound
        return HabitCompletionResult(
            success=True,
            completed=True,
            date=date(2026, 3, 4),
            new_streak=4,
            changed=True,
        )

    async def incomplete_habit(self, habit_id: UUID) -> HabitCompletionResult:
        if self.incomplete_error:
            raise self.incomplete_error
        if not self.exists:
            raise HabitNotFound
        return HabitCompletionResult(
            success=True,
            completed=False,
            date=date(2026, 3, 4),
            new_streak=3,
            changed=True,
        )

    async def delete_habit(self, habit_id: UUID) -> bool:
        if self.delete_error:
            raise self.delete_error
        return True


def _override_habit_service(service: _FakeHabitService) -> None:
    app.dependency_overrides[get_habit_service] = lambda: service
    app.dependency_overrides[get_user_habit_service] = lambda: service


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
        "habit-user@example.com"
    )
    app.dependency_overrides[require_csrf] = lambda: None
    _override_habit_service(_FakeHabitService())
    try:
        async with async_test_client(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/habits/", "/habits/new"])
async def test_habit_pages_return_html(client: AsyncClient, path: str) -> None:
    res = await client.get(path)

    assert_html_response(res, status_code=200)


@pytest.mark.parametrize(
    "path",
    [
        "/habits/?schedule_type=invalid",
        "/habits/?status=all",
        "/habits/?per_page=0",
    ],
)
async def test_habits_list_rejects_invalid_query_params(
    client: AsyncClient,
    path: str,
) -> None:
    res = await client.get(path)

    assert_json_response(res, status_code=422)


async def test_create_habit_returns_303_redirect_on_success(client: AsyncClient) -> None:
    res = await client.post(
        "/habits/",
        data=await with_csrf_form(
            client,
            {"name": "Утренняя зарядка", "schedule_type": "daily"},
            path="/habits/new",
        ),
        follow_redirects=False,
    )

    assert_redirect(res, location="/habits")


async def test_create_habit_rejects_missing_csrf_token_for_form(
    client: AsyncClient,
) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.post(
        "/habits/",
        data={"name": "Утренняя зарядка", "schedule_type": "daily"},
        follow_redirects=False,
    )

    assert_html_response(res, status_code=403)
    assert "Сессия формы истекла" in res.text


async def test_create_habit_rejects_missing_csrf_token_for_json(
    client: AsyncClient,
) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.post(
        "/habits/",
        json={"name": "Утренняя зарядка", "schedule_type": "daily"},
    )

    assert_json_detail(res, status_code=403, detail="Invalid CSRF token")


async def test_create_habit_accepts_valid_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.post(
        "/habits/",
        data=await with_csrf_form(
            client,
            {"name": "Утренняя зарядка", "schedule_type": "daily"},
            path="/habits/new",
        ),
        follow_redirects=False,
    )

    assert_redirect(res, location="/habits")


async def test_get_habit_page_returns_404_when_missing(client: AsyncClient) -> None:
    _override_habit_service(_FakeHabitService(exists=False))

    res = await client.get(f"/habits/{uuid4()}")

    assert_html_response(res, status_code=404)


async def test_get_habit_page_rejects_invalid_uuid_with_422(client: AsyncClient) -> None:
    res = await client.get("/habits/not-a-uuid")

    assert_json_response(res, status_code=422)


async def test_update_habit_returns_success_payload(client: AsyncClient) -> None:
    res = await client.put(
        f"/habits/{uuid4()}",
        json={"name": "Обновленная привычка", "schedule_type": "daily"},
    )

    assert_json_response(res, status_code=200)
    assert res.json() == {"message": "success"}


@pytest.mark.parametrize(
    ("service_kwargs", "expected_status", "expected_code"),
    [
        ({"update_error": ValueError("bad update")}, 400, "bad_request"),
        ({"update_error": HabitNotFound()}, 404, "not_found"),
    ],
)
async def test_update_habit_returns_expected_domain_error(
    client: AsyncClient,
    service_kwargs: dict[str, object],
    expected_status: int,
    expected_code: str,
) -> None:
    _override_habit_service(_FakeHabitService(**service_kwargs))

    res = await client.put(f"/habits/{uuid4()}", json={"name": "Missing"})

    assert_json_response(res, status_code=expected_status)
    assert res.json()["error"]["code"] == expected_code


async def test_update_habit_rejects_invalid_uuid_with_422(client: AsyncClient) -> None:
    res = await client.put("/habits/not-a-uuid", json={"name": "Updated"})

    assert_json_response(res, status_code=422)


@pytest.mark.parametrize(
    ("path_suffix", "expected_completed"),
    [("complete", True), ("incomplete", False)],
)
async def test_habit_toggle_returns_payload_when_ok(
    client: AsyncClient,
    path_suffix: str,
    expected_completed: bool,
) -> None:
    res = await client.patch(f"/habits/{uuid4()}/{path_suffix}")

    assert_json_response(res, status_code=200)
    payload = res.json()
    assert payload["success"] is True
    assert payload["completed"] is expected_completed
    assert payload["date"] == "2026-03-04"
    assert isinstance(payload["new_streak"], int)
    assert isinstance(payload["changed"], bool)


@pytest.mark.parametrize("path_suffix", ["complete", "incomplete"])
async def test_habit_toggle_returns_404_when_missing(
    client: AsyncClient,
    path_suffix: str,
) -> None:
    _override_habit_service(_FakeHabitService(exists=False))

    res = await client.patch(f"/habits/{uuid4()}/{path_suffix}")

    assert_json_response(res, status_code=404)


async def test_complete_habit_rejects_missing_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.patch(f"/habits/{uuid4()}/complete")

    assert_json_detail(res, status_code=403, detail=PUBLIC_ERRORS[403])


@pytest.mark.parametrize("path_suffix", ["complete", "incomplete"])
async def test_habit_toggle_rejects_invalid_uuid_with_422(
    client: AsyncClient,
    path_suffix: str,
) -> None:
    res = await client.patch(f"/habits/not-a-uuid/{path_suffix}")

    assert_json_response(res, status_code=422)


@pytest.mark.parametrize(
    ("path_suffix", "service_kwargs", "expected_status", "expected_detail"),
    [
        ("complete", {"complete_error": ValueError("bad complete")}, 400, PUBLIC_ERRORS[400]),
        (
            "complete",
            {"complete_error": RuntimeError("boom")},
            500,
            PUBLIC_ERRORS[500],
        ),
        (
            "incomplete",
            {"incomplete_error": ValueError("bad incomplete")},
            400,
            PUBLIC_ERRORS[400],
        ),
        (
            "incomplete",
            {"incomplete_error": RuntimeError("boom")},
            500,
            PUBLIC_ERRORS[500],
        ),
    ],
)
async def test_habit_toggle_returns_expected_error(
    client: AsyncClient,
    path_suffix: str,
    service_kwargs: dict[str, object],
    expected_status: int,
    expected_detail: str,
) -> None:
    _override_habit_service(_FakeHabitService(**service_kwargs))

    res = await client.patch(f"/habits/{uuid4()}/{path_suffix}")

    assert_json_detail(res, status_code=expected_status, detail=expected_detail)


async def test_delete_habit_returns_204_when_success(client: AsyncClient) -> None:
    res = await client.delete(f"/habits/{uuid4()}")

    assert res.status_code == 204


async def test_delete_habit_rejects_invalid_uuid_with_422(client: AsyncClient) -> None:
    res = await client.delete("/habits/not-a-uuid")

    assert_json_response(res, status_code=422)
