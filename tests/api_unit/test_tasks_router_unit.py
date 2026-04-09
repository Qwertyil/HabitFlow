from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import AsyncClient

from src.csrf import require_csrf
from src.dependencies import (
    get_task_service,
    get_template_context,
    get_user_task_service,
    require_auth,
)
from src.exceptions import TaskNotFound
from src.main import app
from src.schemas.tasks import TaskInDB
from src.services.tasks import PRIORITY_IDS
from src.exception_handlers import PUBLIC_ERRORS
from src.csrf import ensure_csrf_token
from tests.api_unit.assertions import (
    assert_html_response,
    assert_json_detail,
    assert_json_response,
    assert_redirect,
)
from tests.helpers import async_test_client, make_auth_user, with_csrf_form

pytestmark = pytest.mark.asyncio


def _mk_task(task_id: UUID) -> TaskInDB:
    now = datetime(2026, 1, 1, 0, 0, 0)
    return TaskInDB(
        id=task_id,
        name="t",
        description=None,
        theme_id=None,
        priority_id=PRIORITY_IDS["low"],
        completed_at=None,
        created_at=now,
        updated_at=now,
    )


class _FakeTaskService:
    def __init__(
        self,
        *,
        exists: bool = True,
        complete_error: Exception | None = None,
        incomplete_error: Exception | None = None,
        create_error: Exception | None = None,
        create_returns_none: bool = False,
        update_error: Exception | None = None,
        update_returns_none: bool = False,
        delete_error: Exception | None = None,
    ):
        self.exists = exists
        self.complete_error = complete_error
        self.incomplete_error = incomplete_error
        self.create_error = create_error
        self.create_returns_none = create_returns_none
        self.update_error = update_error
        self.update_returns_none = update_returns_none
        self.delete_error = delete_error

    async def create_task(self, task_data: object) -> TaskInDB | None:
        if self.create_error:
            raise self.create_error
        if self.create_returns_none:
            return None
        return _mk_task(uuid4())

    async def update_task(self, task_id: UUID, task_data: object) -> TaskInDB | None:
        if self.update_error:
            raise self.update_error
        if self.update_returns_none:
            return None
        return _mk_task(task_id)

    async def delete_task(self, task_id: UUID) -> bool:
        if self.delete_error:
            raise self.delete_error
        return True

    async def complete_task(self, task_id: UUID) -> TaskInDB:
        if self.complete_error:
            raise self.complete_error
        if not self.exists:
            raise TaskNotFound
        return _mk_task(task_id).model_copy(update={"completed_at": datetime.now(UTC)})

    async def incomplete_task(self, task_id: UUID) -> TaskInDB:
        if self.incomplete_error:
            raise self.incomplete_error
        if not self.exists:
            raise TaskNotFound
        return _mk_task(task_id).model_copy(update={"completed_at": None})

    async def get_task_priorities(self) -> dict[str, dict[str, str]]:
        return {
            "low": {"name": "Low", "color": "#00FF00"},
            "medium": {"name": "Medium", "color": "#FFFF00"},
            "high": {"name": "High", "color": "#FF0000"},
        }


def _override_task_service(service: _FakeTaskService) -> None:
    app.dependency_overrides[get_task_service] = lambda: service
    app.dependency_overrides[get_user_task_service] = lambda: service


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
        "task-user@example.com"
    )
    app.dependency_overrides[require_csrf] = lambda: None
    _override_task_service(_FakeTaskService())
    try:
        async with async_test_client(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("path_suffix", "expected_completed"),
    [("complete", True), ("incomplete", False)],
)
async def test_task_toggle_returns_payload_when_ok(
    client: AsyncClient,
    path_suffix: str,
    expected_completed: bool,
) -> None:
    task_id = uuid4()
    res = await client.patch(f"/tasks/{task_id}/{path_suffix}")

    assert_json_response(res, status_code=200)
    payload = res.json()
    assert payload["success"] is True
    assert payload["completed"] is expected_completed
    assert payload["task"]["id"] == str(task_id)


@pytest.mark.parametrize("path_suffix", ["complete", "incomplete"])
async def test_task_toggle_returns_404_when_missing(
    client: AsyncClient,
    path_suffix: str,
) -> None:
    _override_task_service(_FakeTaskService(exists=False))

    res = await client.patch(f"/tasks/{uuid4()}/{path_suffix}")

    assert_json_response(res, status_code=404)


@pytest.mark.parametrize(
    ("path_suffix", "service_kwargs"),
    [
        ("complete", {"complete_error": RuntimeError("boom")}),
        ("incomplete", {"incomplete_error": RuntimeError("boom")}),
    ],
)
async def test_task_toggle_returns_500_on_unexpected_error(
    client: AsyncClient,
    path_suffix: str,
    service_kwargs: dict[str, object],
) -> None:
    _override_task_service(_FakeTaskService(**service_kwargs))

    res = await client.patch(f"/tasks/{uuid4()}/{path_suffix}")

    assert_json_detail(res, status_code=500, detail=PUBLIC_ERRORS[500])


async def test_create_task_returns_redirect_on_success(client: AsyncClient) -> None:
    res = await client.post(
        "/tasks/",
        data=await with_csrf_form(client, {"name": "Task", "priority": "low"}, path="/tasks/new"),
        follow_redirects=False,
    )

    assert_redirect(res, location="/tasks")


@pytest.mark.parametrize(
    ("service_kwargs", "expected_status", "expected_message"),
    [
        ({"create_error": ValueError("bad task")}, 400, "bad task"),
        ({"create_error": RuntimeError("broken")}, 500, "broken"),
        ({"create_returns_none": True}, 500, "Задача не создана"),
    ],
)
async def test_create_task_returns_html_error_for_failures(
    client: AsyncClient,
    service_kwargs: dict[str, object],
    expected_status: int,
    expected_message: str,
) -> None:
    _override_task_service(_FakeTaskService(**service_kwargs))

    res = await client.post(
        "/tasks/",
        data=await with_csrf_form(client, {"name": "Task", "priority": "low"}, path="/tasks/new"),
    )

    assert_html_response(res, status_code=expected_status)
    assert expected_message in res.text


async def test_create_task_rejects_missing_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.post("/tasks/", data={"name": "Task", "priority": "low"})

    assert_html_response(res, status_code=403)
    assert "Сессия формы истекла" in res.text


async def test_complete_task_rejects_missing_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.patch(f"/tasks/{uuid4()}/complete")

    assert_json_detail(res, status_code=403, detail=PUBLIC_ERRORS[403])


async def test_create_task_accepts_valid_csrf_token(client: AsyncClient) -> None:
    app.dependency_overrides.pop(require_csrf, None)

    res = await client.post(
        "/tasks/",
        data=await with_csrf_form(client, {"name": "Task", "priority": "low"}, path="/tasks/new"),
        follow_redirects=False,
    )

    assert_redirect(res, location="/tasks")


async def test_update_task_returns_success_payload(client: AsyncClient) -> None:
    res = await client.put(f"/tasks/{uuid4()}", json={"name": "Updated"})

    assert_json_response(res, status_code=200)
    assert res.json() == {"message": "success"}


@pytest.mark.parametrize(
    ("service_kwargs", "expected_status", "expected_body"),
    [
        (
            {"update_error": ValueError("bad update")},
            400,
            {"error": {"code": "bad_request", "message": "bad update"}},
        ),
        (
            {"update_error": TaskNotFound()},
            404,
            {"error": {"code": "not_found", "message": "Задача не найдена"}},
        ),
        (
            {"update_error": RuntimeError("failed update")},
            500,
            {"error": {"code": "internal_error", "message": "Internal server error"}},
        ),
        (
            {"update_returns_none": True},
            500,
            {"error": {"code": "internal_error", "message": "Задача не обновлена"}},
        ),
    ],
)
async def test_update_task_returns_expected_error_payload(
    client: AsyncClient,
    service_kwargs: dict[str, object],
    expected_status: int,
    expected_body: dict[str, object],
) -> None:
    _override_task_service(_FakeTaskService(**service_kwargs))

    res = await client.put(f"/tasks/{uuid4()}", json={"name": "Updated"})

    assert_json_response(res, status_code=expected_status)
    assert res.json() == expected_body


async def test_delete_task_returns_204_when_success(client: AsyncClient) -> None:
    res = await client.delete(f"/tasks/{uuid4()}")

    assert res.status_code == 204


async def test_delete_task_returns_500_when_runtime_error(client: AsyncClient) -> None:
    _override_task_service(_FakeTaskService(delete_error=RuntimeError("cannot delete")))

    res = await client.delete(f"/tasks/{uuid4()}")

    assert_json_detail(res, status_code=500, detail=PUBLIC_ERRORS[500])
