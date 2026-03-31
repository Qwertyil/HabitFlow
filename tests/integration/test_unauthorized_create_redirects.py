from collections.abc import AsyncGenerator

import pytest
from fastapi import Request
from httpx import AsyncClient

from src.database.connection import get_db, get_engine
from src.main import app
from tests.api_unit.assertions import assert_redirect
from tests.helpers import async_test_client, with_csrf_form

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def anonymous_client(
    engine_async, session_factory_async
) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db(request: Request):
        async with session_factory_async() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_engine] = lambda: engine_async

    try:
        async with async_test_client(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("submit_path", "form_path", "payload", "expected_location"),
    [
        (
            "/themes/",
            "/themes/new",
            {"name": "Новая тема"},
            "/auth/login?next=%2Fthemes%2F",
        ),
        (
            "/tasks/",
            "/tasks/new",
            {"name": "Новая задача", "priority": "low"},
            "/auth/login?next=%2Ftasks%2F",
        ),
        (
            "/habits/",
            "/habits/new",
            {"name": "Новая привычка", "schedule_type": "daily"},
            "/auth/login?next=%2Fhabits%2F",
        ),
    ],
)
async def test_unauthorized_create_form_redirects_to_login(
    anonymous_client: AsyncClient,
    submit_path: str,
    form_path: str,
    payload: dict[str, str],
    expected_location: str,
) -> None:
    response = await anonymous_client.post(
        submit_path,
        data=await with_csrf_form(anonymous_client, payload, path=form_path),
        follow_redirects=False,
    )

    assert_redirect(response, location=expected_location)
