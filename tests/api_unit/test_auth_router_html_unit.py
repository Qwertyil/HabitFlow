from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from typing import Never
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from httpx import AsyncClient
from starlette.middleware.sessions import SessionMiddleware

import src.main as main_module
from src.dependencies import _is_html_request, get_current_user, get_login_service, get_oauth_service, get_registration_service
from src.exceptions import (
    EmailAlreadyExistsError,
    OAuthAuthorizationCodeMissingError,
    OAuthConfigurationError,
    OAuthEmailNotVerifiedError,
    OAuthProviderRejectedError,
    OAuthProviderUnavailableError,
    OAuthStateInvalidError,
)
from src.routers import auth as auth_module
from src.routers.auth import _normalize_next, router as auth_router
from src.schemas.auth import AuthUser
from tests.api_unit.auth_router_shared import (  # noqa: F401
    _FakeAuthService,
    _FakeLoginService,
    _FakeOAuthService,
    _FakeRegistrationService,
    _extract_form,
    _extract_google_oauth_href,
    configure_google_oauth,
)
from tests.helpers import async_test_client, extract_csrf_token, make_auth_user

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("next_value", "expected"),
    [
        (None, "/"),
        ("", "/"),
        ("/tasks", "/tasks"),
        ("tasks", "/"),
        ("//evil.example", "/"),
        ("https://evil.example/path", "/"),
    ],
)
async def test_normalize_next_rejects_unsafe_targets(
    next_value: str | None,
    expected: str,
) -> None:
    assert _normalize_next(next_value) == expected


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"accept": "text/html"}, True),
        ({"content-type": "application/x-www-form-urlencoded"}, True),
        ({"content-type": "multipart/form-data; boundary=abc"}, True),
        ({"accept": "application/json", "content-type": "application/json"}, False),
    ],
)
async def test_is_html_request_detects_browser_requests(
    headers: dict[str, str],
    expected: bool,
) -> None:
    app = FastAPI()

    @app.get("/probe")
    async def probe(request: Request) -> dict[str, bool]:
        return {"is_html": _is_html_request(request)}

    async with async_test_client(app) as http_client:
        res = await http_client.get("/probe", headers=headers)

    assert res.status_code == 200
    assert res.json() == {"is_html": expected}


@pytest.fixture
async def client() -> AsyncGenerator[
    tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
    None,
]:
    app = FastAPI()
    app.state.settings = main_module.settings
    fake_login_service = _FakeLoginService()
    fake_registration_service = _FakeRegistrationService()
    fake_oauth_service = _FakeOAuthService()
    fake_auth_service = _FakeAuthService()
    fake_auth_service.login_service = fake_login_service
    fake_auth_service.registration_service = fake_registration_service
    fake_auth_service.oauth_service = fake_oauth_service
    current_user_state = {"value": None}

    app.add_middleware(
        SessionMiddleware,
        secret_key=main_module.settings.session_secret_key,
        session_cookie=main_module.settings.UI_SESSION_COOKIE_NAME,
    )
    app.mount("/static", StaticFiles(directory="src/static"), name="static")
    app.include_router(auth_router)

    @app.get("/__test/session")
    async def session_probe(request: Request) -> dict[str, object]:
        return dict(request.session)

    @app.post("/__test/session")
    async def session_mutation(request: Request) -> dict[str, object]:
        payload = await request.json()
        if not isinstance(payload, dict):
            return dict(request.session)
        for key, value in payload.items():
            request.session[key] = value
        return dict(request.session)

    async def override_current_user() -> AuthUser | None:
        return current_user_state["value"]

    app.dependency_overrides[get_login_service] = lambda: fake_login_service
    app.dependency_overrides[get_registration_service] = lambda: fake_registration_service
    app.dependency_overrides[get_oauth_service] = lambda: fake_oauth_service
    app.dependency_overrides[get_current_user] = override_current_user
    app.state.current_user_state = current_user_state

    try:
        async with async_test_client(app) as http_client:
            yield http_client, fake_auth_service, fake_login_service, fake_registration_service, fake_oauth_service, current_user_state
    finally:
        app.dependency_overrides.clear()


async def test_login_page_renders_csrf_and_normalizes_unsafe_next(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.get(
        "/auth/login?next=https://evil.example",
        headers={"Accept": "text/html"},
    )

    assert res.status_code == 200
    assert 'name="csrf_token"' in res.text
    assert 'name="next" value="/"' in res.text
    assert _extract_google_oauth_href(res.text) == "/auth/google/start?next=/"

    login_form = _extract_form(res.text, "/auth/login")
    assert "/auth/google/start" not in login_form


async def test_login_page_renders_google_oauth_link_with_next(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.get(
        "/auth/login?next=/tasks?filter=today",
        headers={"Accept": "text/html"},
    )

    assert res.status_code == 200
    assert (
        _extract_google_oauth_href(res.text)
        == "/auth/google/start?next=/tasks%3Ffilter%3Dtoday"
    )


async def test_login_page_hides_google_oauth_when_not_configured(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client
    main_module.settings.GOOGLE_OAUTH_CLIENT_ID = None
    main_module.settings.GOOGLE_OAUTH_CLIENT_SECRET = None
    main_module.settings.GOOGLE_OAUTH_REDIRECT_URI = None

    res = await http_client.get(
        "/auth/login?next=/tasks?filter=today",
        headers={"Accept": "text/html"},
    )

    assert res.status_code == 200
    assert "/auth/google/start" not in res.text


async def test_login_page_redirects_authenticated_user_to_safe_next(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, current_user_state = client
    current_user_state["value"] = make_auth_user()

    res = await http_client.get(
        "/auth/login?next=https://evil.example",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/"


async def test_google_start_redirects_to_google_and_stores_state_in_ui_session(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client

    res = await http_client.get(
        "/auth/google/start?next=https://evil.example",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"].startswith(
        "https://accounts.google.com/o/oauth2/v2/auth?"
    )

    session = await http_client.get("/__test/session")
    assert session.status_code == 200

    google_session = session.json()["google_oauth"]
    assert google_session["next"] == "/"
    assert google_session["state"] == "fake-state"
    assert google_session["issued_at"] == "2026-03-08T12:00:00Z"
    assert fake_auth_service.google_start_calls == [{"next_url": "/"}]

    authorize_query = parse_qs(urlsplit(res.headers["location"]).query)
    assert authorize_query["state"] == [google_session["state"]]


async def test_google_start_redirects_authenticated_user_to_safe_next(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, current_user_state = client
    current_user_state["value"] = make_auth_user()

    res = await http_client.get(
        "/auth/google/start?next=https://evil.example",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/"


async def test_google_callback_creates_local_session_and_redirects_to_saved_next(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client

    start_res = await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert start_res.status_code == 303

    session_before = await http_client.get("/__test/session")
    stored_state = session_before.json()["google_oauth"]["state"]

    res = await http_client.get(
        f"/auth/google/callback?code=oauth-code&state={stored_state}",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/tasks"
    assert main_module.settings.AUTH_SESSION_COOKIE_NAME in res.headers.get("set-cookie", "")
    assert fake_auth_service.oauth_user_calls == [
        {
            "email": "oauth@example.com",
            "provider": "google",
            "provider_user_id": "google-user-123",
        }
    ]
    assert fake_auth_service.created_session_for == [str(fake_auth_service.oauth_user_result.id)]
    assert fake_auth_service.google_callback_calls == [
        {
            "oauth_session": {
                "state": "fake-state",
                "next": "/tasks",
                "issued_at": "2026-03-08T12:00:00Z",
            },
            "provided_state": "fake-state",
            "provider_error": None,
            "code": "oauth-code",
        }
    ]

    session_after = await http_client.get("/__test/session")
    assert "google_oauth" not in session_after.json()


async def test_google_callback_returns_html_error_and_consumes_state_on_provider_error(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthProviderRejectedError()

    start_res = await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert start_res.status_code == 303

    session_before = await http_client.get("/__test/session")
    stored_state = session_before.json()["google_oauth"]["state"]

    res = await http_client.get(
        f"/auth/google/callback?error=access_denied&state={stored_state}",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 400
    assert res.headers["content-type"].startswith("text/html")
    assert "Google отклонил запрос на вход." in res.text
    assert fake_auth_service.oauth_user_calls == []
    assert fake_auth_service.created_session_for == []

    session_after = await http_client.get("/__test/session")
    assert "google_oauth" not in session_after.json()


async def test_google_callback_handles_missing_oauth_configuration(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthConfigurationError(
        "Google OAuth is not configured"
    )

    start_res = await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert start_res.status_code == 303

    session_before = await http_client.get("/__test/session")
    stored_state = session_before.json()["google_oauth"]["state"]

    res = await http_client.get(
        f"/auth/google/callback?code=oauth-code&state={stored_state}",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 503
    assert res.headers["content-type"].startswith("text/html")
    assert "Вход через Google недоступен" in res.text

    session_after = await http_client.get("/__test/session")
    assert "google_oauth" not in session_after.json()


async def test_google_callback_rejects_invalid_state_as_one_time_token(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthStateInvalidError()

    start_res = await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert start_res.status_code == 303

    res = await http_client.get(
        "/auth/google/callback?code=oauth-code&state=wrong-state",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 400
    assert fake_auth_service.oauth_user_calls == []
    assert fake_auth_service.created_session_for == []

    session_after = await http_client.get("/__test/session")
    assert "google_oauth" not in session_after.json()


async def test_google_callback_redirects_authenticated_user_when_state_was_already_consumed(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    fake_auth_service.google_callback_error = OAuthStateInvalidError()
    current_user_state["value"] = make_auth_user()

    res = await http_client.get(
        "/auth/google/callback?code=oauth-code&state=already-used-state",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/"
    assert fake_auth_service.oauth_user_calls == []
    assert fake_auth_service.created_session_for == []


async def test_google_callback_rejects_expired_state(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthStateInvalidError()

    start_res = await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert start_res.status_code == 303

    session_before = await http_client.get("/__test/session")
    oauth_session = session_before.json()["google_oauth"]
    expired_issued_at = (
        datetime.now(UTC) - timedelta(seconds=main_module.settings.GOOGLE_OAUTH_STATE_TTL + 1)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    oauth_session["issued_at"] = expired_issued_at
    await http_client.post("/__test/session", json={"google_oauth": oauth_session})

    res = await http_client.get(
        f"/auth/google/callback?code=oauth-code&state={oauth_session['state']}",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 400
    assert fake_auth_service.oauth_user_calls == []
    assert fake_auth_service.created_session_for == []

    session_after = await http_client.get("/__test/session")
    assert "google_oauth" not in session_after.json()


async def test_google_callback_rejects_state_with_invalid_issued_at(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthStateInvalidError()

    start_res = await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert start_res.status_code == 303

    session_before = await http_client.get("/__test/session")
    oauth_session = session_before.json()["google_oauth"]
    oauth_session["issued_at"] = "not-a-timestamp"
    await http_client.post("/__test/session", json={"google_oauth": oauth_session})

    res = await http_client.get(
        f"/auth/google/callback?code=oauth-code&state={oauth_session['state']}",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 400
    assert fake_auth_service.oauth_user_calls == []
    assert fake_auth_service.created_session_for == []

    session_after = await http_client.get("/__test/session")
    assert "google_oauth" not in session_after.json()


async def test_google_callback_rejects_missing_code(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthAuthorizationCodeMissingError()

    await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    res = await http_client.get(
        "/auth/google/callback?state=fake-state",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 400
    assert "не содержит кода авторизации" in res.text


async def test_google_callback_rejects_unverified_email(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthEmailNotVerifiedError()

    await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    res = await http_client.get(
        "/auth/google/callback?code=oauth-code&state=fake-state",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 403
    assert "Google не подтвердил email" in res.text


async def test_google_callback_handles_provider_unavailable(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.google_callback_error = OAuthProviderUnavailableError()

    await http_client.get(
        "/auth/google/start?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    res = await http_client.get(
        "/auth/google/callback?code=oauth-code&state=fake-state",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 502
    assert "Google временно недоступен" in res.text

async def test_register_page_redirects_authenticated_user(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, current_user_state = client
    current_user_state["value"] = make_auth_user()

    res = await http_client.get(
        "/auth/register?next=/tasks",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/tasks"


async def test_register_page_renders_google_oauth_link_with_next(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.get(
        "/auth/register?next=/habits?page=2",
        headers={"Accept": "text/html"},
    )

    assert res.status_code == 200
    assert (
        _extract_google_oauth_href(res.text)
        == "/auth/google/start?next=/habits%3Fpage%3D2"
    )

    register_form = _extract_form(res.text, "/auth/register")
    assert "/auth/google/start" not in register_form


async def test_register_page_hides_google_oauth_when_not_configured(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client
    main_module.settings.GOOGLE_OAUTH_CLIENT_ID = None
    main_module.settings.GOOGLE_OAUTH_CLIENT_SECRET = None
    main_module.settings.GOOGLE_OAUTH_REDIRECT_URI = None

    res = await http_client.get(
        "/auth/register?next=/habits?page=2",
        headers={"Accept": "text/html"},
    )

    assert res.status_code == 200
    assert "/auth/google/start" not in res.text


async def test_login_form_rejects_missing_csrf_token(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/login",
        headers={"Accept": "text/html"},
        data={"email": "user@example.com", "password": "strong-pass-123", "next": "/tasks"},
    )

    assert res.status_code == 403
    assert res.headers["content-type"].startswith("text/html")
    assert "Сессия формы истекла или стала недействительной." in res.text
    assert 'name="csrf_token"' in res.text


async def test_login_form_rejects_invalid_csrf_token(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    page = await http_client.get("/auth/login", headers={"Accept": "text/html"})
    assert extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/login",
        headers={"Accept": "text/html"},
        data={
            "email": "user@example.com",
            "password": "strong-pass-123",
            "csrf_token": "invalid-token",
            "next": "/tasks",
        },
    )

    assert res.status_code == 403
    assert res.headers["content-type"].startswith("text/html")
    assert "Сессия формы истекла или стала недействительной." in res.text
    assert 'value="user@example.com"' in res.text


async def test_register_form_rejects_invalid_csrf_token_with_html_error(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    page = await http_client.get("/auth/register", headers={"Accept": "text/html"})
    assert extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/register",
        headers={"Accept": "text/html"},
        data={
            "email": "new@example.com",
            "password": "strong-pass-123",
            "csrf_token": "invalid-token",
            "next": "/tasks",
        },
    )

    assert res.status_code == 403
    assert res.headers["content-type"].startswith("text/html")
    assert "Сессия формы истекла или стала недействительной." in res.text
    assert 'value="new@example.com"' in res.text


async def test_login_form_redirects_after_success(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.authenticate_result = make_auth_user()

    page = await http_client.get("/auth/login?next=/tasks", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/login",
        headers={"Accept": "text/html"},
        data={
            "email": "user@example.com",
            "password": "strong-pass-123",
            "csrf_token": csrf_token,
            "next": "/tasks",
        },
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/tasks"
    assert main_module.settings.AUTH_SESSION_COOKIE_NAME in res.headers.get("set-cookie", "")


async def test_login_json_returns_user_and_sets_cookie(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.authenticate_result = make_auth_user()

    res = await http_client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "strong-pass-123"},
    )

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["email"] == "user@example.com"
    assert main_module.settings.AUTH_SESSION_COOKIE_NAME in res.headers.get("set-cookie", "")


async def test_login_json_returns_409_for_authenticated_user_without_auth_attempt(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    current_user_state["value"] = make_auth_user()

    res = await http_client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "strong-pass-123"},
    )

    assert res.status_code == 409
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["detail"] == "Already authenticated"
    assert fake_auth_service.authenticate_calls == []
    assert fake_auth_service.created_session_for == []


@pytest.mark.parametrize(
    ("path", "payload", "prepare_service"),
    [
        (
            "/auth/login",
            {"email": "user@example.com", "password": "strong-pass-123"},
            lambda service: setattr(service, "authenticate_result", make_auth_user()),
        ),
        (
            "/auth/register",
            {"email": "new@example.com", "password": "strong-pass-123"},
            lambda service: setattr(service, "register_result", make_auth_user("new@example.com")),
        ),
    ],
)
async def test_json_auth_endpoints_do_not_render_html_templates(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict[str, str],
    prepare_service: Callable[[_FakeAuthService], None],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    prepare_service(fake_auth_service)

    def fail_on_render(*args, **kwargs) -> Never:  # noqa: ANN002, ANN003
        raise AssertionError("HTML template render should not happen for JSON requests")

    monkeypatch.setattr(auth_module, "_render_auth_template", fail_on_render)

    res = await http_client.post(path, json=payload)

    assert res.status_code in {200, 201}
    assert res.headers["content-type"].startswith("application/json")


async def test_login_json_rejects_invalid_credentials(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.authenticate_result = None

    res = await http_client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert res.status_code == 401
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["detail"] == "Invalid email or password"


async def test_login_json_rejects_invalid_payload_with_422(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/login",
        json={"email": "not-an-email", "password": "short"},
    )

    assert res.status_code == 422
    assert res.headers["content-type"].startswith("application/json")


async def test_login_json_rejects_malformed_json_body(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/login",
        content="{",
        headers={"Content-Type": "application/json"},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Malformed JSON body"


async def test_login_rejects_unsupported_media_type_with_415(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/login",
        content="email=user@example.com",
        headers={"Content-Type": "text/plain"},
    )

    assert res.status_code == 415
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["detail"] == "Unsupported Media Type"


async def test_login_form_returns_generic_error_on_invalid_credentials(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.authenticate_result = None

    page = await http_client.get("/auth/login", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/login",
        headers={"Accept": "text/html"},
        data={
            "email": "user@example.com",
            "password": "wrong-password",
            "csrf_token": csrf_token,
            "next": "/",
        },
    )

    assert res.status_code == 401
    assert "Неверный email или пароль." in res.text
    assert "wrong-password" not in res.text


async def test_login_form_returns_validation_error_for_invalid_payload(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    page = await http_client.get("/auth/login", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/login",
        headers={"Accept": "text/html"},
        data={
            "email": "not-an-email",
            "password": "strong-pass-123",
            "csrf_token": csrf_token,
            "next": "/tasks",
        },
    )

    assert res.status_code == 400
    assert "Введите корректный email." in res.text
    assert 'value="not-an-email"' in res.text


async def test_register_form_returns_validation_error_and_preserves_email(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    page = await http_client.get("/auth/register", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/register",
        headers={"Accept": "text/html"},
        data={
            "email": "new@example.com",
            "password": "short",
            "csrf_token": csrf_token,
            "next": "/tasks",
        },
    )

    assert res.status_code == 400
    assert "Пароль должен быть длиной от 8 до 256 символов." in res.text
    assert 'value="new@example.com"' in res.text


async def test_register_form_returns_detailed_validation_errors_for_invalid_email_and_password(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    page = await http_client.get("/auth/register", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/register",
        headers={"Accept": "text/html"},
        data={
            "email": "bad-email",
            "password": "short",
            "csrf_token": csrf_token,
            "next": "/tasks",
        },
    )

    assert res.status_code == 400
    assert "Введите корректный email." in res.text
    assert "Пароль должен быть длиной от 8 до 256 символов." in res.text
    assert 'value="bad-email"' in res.text


async def test_register_form_redirects_after_success(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.register_result = make_auth_user("new@example.com")

    page = await http_client.get("/auth/register?next=/tasks", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/register",
        headers={"Accept": "text/html"},
        data={
            "email": "new@example.com",
            "password": "strong-pass-123",
            "csrf_token": csrf_token,
            "next": "/tasks",
        },
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/tasks"
    assert main_module.settings.AUTH_SESSION_COOKIE_NAME in res.headers.get("set-cookie", "")


async def test_register_form_returns_conflict_error_when_email_exists(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.register_error = EmailAlreadyExistsError()

    page = await http_client.get("/auth/register", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    res = await http_client.post(
        "/auth/register",
        headers={"Accept": "text/html"},
        data={
            "email": "new@example.com",
            "password": "strong-pass-123",
            "csrf_token": csrf_token,
            "next": "/tasks",
        },
    )

    assert res.status_code == 409
    assert "Пользователь с таким email уже существует." in res.text


async def test_register_json_returns_user_and_sets_cookie(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.register_result = make_auth_user("new@example.com")

    res = await http_client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "strong-pass-123"},
    )

    assert res.status_code == 201
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["email"] == "new@example.com"
    assert main_module.settings.AUTH_SESSION_COOKIE_NAME in res.headers.get("set-cookie", "")


async def test_register_json_returns_409_for_authenticated_user_without_register_attempt(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    current_user_state["value"] = make_auth_user()

    res = await http_client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "strong-pass-123"},
    )

    assert res.status_code == 409
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["detail"] == "Already authenticated"
    assert fake_auth_service.register_calls == []
    assert fake_auth_service.created_session_for == []


async def test_register_json_rejects_invalid_payload_with_422(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/register",
        json={"email": "bad-email", "password": "short"},
    )

    assert res.status_code == 422
    assert res.headers["content-type"].startswith("application/json")


async def test_register_json_returns_conflict_when_email_exists(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client
    fake_auth_service.register_error = EmailAlreadyExistsError()

    res = await http_client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "strong-pass-123"},
    )

    assert res.status_code == 409
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["detail"] == "Email already exists"


async def test_register_json_rejects_malformed_json_body(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/register",
        content="{",
        headers={"Content-Type": "application/json"},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "Malformed JSON body"


async def test_register_json_rejects_non_object_json_body(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/register",
        content='["not", "an", "object"]',
        headers={"Content-Type": "application/json"},
    )

    assert res.status_code == 400
    assert res.json()["detail"] == "JSON body must be an object"


async def test_register_rejects_unsupported_media_type_with_415(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, _, _, _, _, _state = client

    res = await http_client.post(
        "/auth/register",
        content="<email>new@example.com</email>",
        headers={"Content-Type": "application/xml"},
    )

    assert res.status_code == 415
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["detail"] == "Unsupported Media Type"


async def test_logout_form_clears_cookie_and_redirects_home(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    page = await http_client.get("/auth/login", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    current_user = make_auth_user()
    http_client.cookies.set(main_module.settings.AUTH_SESSION_COOKIE_NAME, "session-123")
    current_user_state["value"] = current_user

    res = await http_client.post(
        "/auth/logout",
        headers={"Accept": "text/html"},
        data={"csrf_token": csrf_token, "next": "/"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/"
    assert fake_auth_service.logout_calls == [("session-123", str(current_user.id))]
    assert f"{main_module.settings.AUTH_SESSION_COOKIE_NAME}=" in res.headers.get("set-cookie", "")


async def test_logout_form_normalizes_unsafe_next_target(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    page = await http_client.get("/auth/login", headers={"Accept": "text/html"})
    csrf_token = extract_csrf_token(page.text)

    current_user = make_auth_user()
    http_client.cookies.set(main_module.settings.AUTH_SESSION_COOKIE_NAME, "session-unsafe")
    current_user_state["value"] = current_user

    res = await http_client.post(
        "/auth/logout",
        headers={"Accept": "text/html"},
        data={"csrf_token": csrf_token, "next": "https://evil.example"},
        follow_redirects=False,
    )

    assert res.status_code == 303
    assert res.headers["location"] == "/"
    assert fake_auth_service.logout_calls == [("session-unsafe", str(current_user.id))]


async def test_logout_form_rejects_invalid_csrf_token_with_html_error(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    page = await http_client.get("/auth/login", headers={"Accept": "text/html"})
    assert extract_csrf_token(page.text)

    current_user_state["value"] = make_auth_user()

    res = await http_client.post(
        "/auth/logout",
        headers={"Accept": "text/html"},
        data={"csrf_token": "invalid-token", "next": "/"},
    )

    assert res.status_code == 403
    assert res.headers["content-type"].startswith("text/html")
    assert "Не удалось выполнить выход" in res.text
    assert "Сессия формы истекла или стала недействительной." in res.text
    assert fake_auth_service.logout_calls == []


async def test_logout_json_logs_out_and_clears_cookie(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    current_user = make_auth_user()
    current_user_state["value"] = current_user
    http_client.cookies.set(main_module.settings.AUTH_SESSION_COOKIE_NAME, "session-json")

    res = await http_client.post("/auth/logout", json={"next": "/tasks"})

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    assert res.json() == {"message": "Logged out"}
    assert fake_auth_service.logout_calls == [("session-json", str(current_user.id))]
    assert f"{main_module.settings.AUTH_SESSION_COOKIE_NAME}=" in res.headers.get("set-cookie", "")


async def test_logout_json_without_user_or_session_skips_service_call(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, _state = client

    res = await http_client.post("/auth/logout", json={})

    assert res.status_code == 401
    assert res.json() == {"detail": "Authentication required"}
    assert fake_auth_service.logout_calls == []


async def test_logout_rejects_unsupported_media_type_with_415(
    client: tuple[AsyncClient, _FakeAuthService, _FakeLoginService, _FakeRegistrationService, _FakeOAuthService, dict[str, AuthUser | None]],
) -> None:
    http_client, fake_auth_service, _, _, _, current_user_state = client
    current_user_state["value"] = make_auth_user()

    res = await http_client.post(
        "/auth/logout",
        content="next=/tasks",
        headers={"Content-Type": "text/plain"},
    )

    assert res.status_code == 415
    assert res.headers["content-type"].startswith("application/json")
    assert res.json()["detail"] == "Unsupported Media Type"
    assert fake_auth_service.logout_calls == []
