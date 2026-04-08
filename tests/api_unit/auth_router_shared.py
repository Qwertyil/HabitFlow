from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

import src.main as main_module
from src.schemas.auth import AuthUser
from tests.helpers import make_auth_user


class _FakeLoginService:
    def __init__(self) -> None:
        self.authenticate_result: AuthUser | None = None
        self.authenticate_calls: list[object] = []
        self.created_session_for: list[str] = []
        self.logout_calls: list[tuple[str, str]] = []
        self.resolved_user: AuthUser | None = None
        self.resolve_calls: list[str] = []

    async def authenticate(self, payload) -> AuthUser | None:  # noqa: ANN001
        self.authenticate_calls.append(payload)
        return self.authenticate_result

    async def create_session(self, user_id) -> str:  # noqa: ANN001
        self.created_session_for.append(str(user_id))
        return "session-123"

    async def logout(self, session_id: str, user_id) -> None:  # noqa: ANN001
        self.logout_calls.append((session_id, str(user_id)))

    async def resolve_user(self, session_id: str) -> AuthUser | None:
        self.resolve_calls.append(session_id)
        return self.resolved_user


class _FakeRegistrationService:
    def __init__(self) -> None:
        self.register_result = make_auth_user("new@example.com")
        self.register_error: Exception | None = None
        self.register_calls: list[object] = []

    async def register(self, payload) -> AuthUser:  # noqa: ANN001
        self.register_calls.append(payload)
        if self.register_error is not None:
            raise self.register_error
        return self.register_result


class _FakeOAuthService:
    def __init__(self) -> None:
        self.oauth_user_result: AuthUser = make_auth_user("oauth@example.com")
        self.oauth_user_error: Exception | None = None
        self.google_start_error: Exception | None = None
        self.google_callback_error: Exception | None = None
        self.oauth_user_calls: list[dict[str, str]] = []
        self.google_start_calls: list[dict[str, str]] = []
        self.google_callback_calls: list[dict[str, object]] = []
        self.created_session_for: list[str] = []

    def start_google_oauth_login(self, *, next_url: str) -> SimpleNamespace:
        self.google_start_calls.append({"next_url": next_url})
        if self.google_start_error is not None:
            raise self.google_start_error
        return SimpleNamespace(
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth?state=fake-state",
            session_payload={
                "state": "fake-state",
                "next": next_url,
                "issued_at": "2026-03-08T12:00:00Z",
            },
        )

    async def complete_google_oauth_login(
        self,
        *,
        oauth_session: object,
        provided_state: object,
        provider_error: object,
        code: object,
    ) -> SimpleNamespace:
        self.google_callback_calls.append(
            {
                "oauth_session": oauth_session,
                "provided_state": provided_state,
                "provider_error": provider_error,
                "code": code,
            }
        )
        if self.google_callback_error is not None:
            raise self.google_callback_error

        self.oauth_user_calls.append(
            {
                "email": "oauth@example.com",
                "provider": "google",
                "provider_user_id": "google-user-123",
            }
        )
        self.created_session_for.append(str(self.oauth_user_result.id))
        next_url = "/"
        if isinstance(oauth_session, dict):
            next_url = str(oauth_session.get("next") or "/")
        return SimpleNamespace(
            next_url=next_url,
            session_id="session-123",
            user=self.oauth_user_result,
        )

    async def get_or_create_oauth_user(
        self,
        *,
        email: str,
        provider: str,
        provider_user_id: str,
    ) -> AuthUser:
        self.oauth_user_calls.append(
            {
                "email": email,
                "provider": provider,
                "provider_user_id": provider_user_id,
            }
        )
        if self.oauth_user_error is not None:
            raise self.oauth_user_error
        return self.oauth_user_result


class _FakeAuthService:
    """Legacy facade for backward compatibility with existing tests."""

    def __init__(self) -> None:
        self.login_service = _FakeLoginService()
        self.registration_service = _FakeRegistrationService()
        self.oauth_service = _FakeOAuthService()

    @property
    def register_result(self):
        return self.registration_service.register_result

    @register_result.setter
    def register_result(self, value):
        self.registration_service.register_result = value

    @property
    def register_error(self):
        return self.registration_service.register_error

    @register_error.setter
    def register_error(self, value):
        self.registration_service.register_error = value

    @property
    def register_calls(self):
        return self.registration_service.register_calls

    @property
    def authenticate_result(self):
        return self.login_service.authenticate_result

    @authenticate_result.setter
    def authenticate_result(self, value):
        self.login_service.authenticate_result = value

    @property
    def authenticate_calls(self):
        return self.login_service.authenticate_calls

    @property
    def oauth_user_result(self):
        return self.oauth_service.oauth_user_result

    @oauth_user_result.setter
    def oauth_user_result(self, value):
        self.oauth_service.oauth_user_result = value

    @property
    def oauth_user_error(self):
        return self.oauth_service.oauth_user_error

    @oauth_user_error.setter
    def oauth_user_error(self, value):
        self.oauth_service.oauth_user_error = value

    @property
    def oauth_user_calls(self):
        return self.oauth_service.oauth_user_calls

    @property
    def google_start_error(self):
        return self.oauth_service.google_start_error

    @google_start_error.setter
    def google_start_error(self, value):
        self.oauth_service.google_start_error = value

    @property
    def google_callback_error(self):
        return self.oauth_service.google_callback_error

    @google_callback_error.setter
    def google_callback_error(self, value):
        self.oauth_service.google_callback_error = value

    @property
    def google_start_calls(self):
        return self.oauth_service.google_start_calls

    @property
    def google_callback_calls(self):
        return self.oauth_service.google_callback_calls

    @property
    def created_session_for(self):
        return self.login_service.created_session_for + self.oauth_service.created_session_for

    @property
    def logout_calls(self):
        return self.login_service.logout_calls

    async def register(self, payload) -> AuthUser:  # noqa: ANN001
        return await self.registration_service.register(payload)

    async def authenticate(self, payload) -> AuthUser | None:  # noqa: ANN001
        return await self.login_service.authenticate(payload)

    async def get_or_create_oauth_user(
        self,
        *,
        email: str,
        provider: str,
        provider_user_id: str,
    ) -> AuthUser:
        return await self.oauth_service.get_or_create_oauth_user(
            email=email,
            provider=provider,
            provider_user_id=provider_user_id,
        )

    async def login_create_session(self, user_id) -> str:  # noqa: ANN001
        return await self.login_service.create_session(user_id)

    async def logout(self, session_id: str, user_id) -> None:  # noqa: ANN001
        await self.login_service.logout(session_id, user_id)

    def start_google_oauth_login(self, *, next_url: str) -> SimpleNamespace:
        return self.oauth_service.start_google_oauth_login(next_url=next_url)

    async def complete_google_oauth_login(
        self,
        *,
        oauth_session: object,
        provided_state: object,
        provider_error: object,
        code: object,
    ) -> SimpleNamespace:
        return await self.oauth_service.complete_google_oauth_login(
            oauth_session=oauth_session,
            provided_state=provided_state,
            provider_error=provider_error,
            code=code,
        )

    async def resolve_user(self, session_id: str) -> AuthUser | None:
        return await self.login_service.resolve_user(session_id)


def _extract_form(html: str, action: str) -> str:
    match = re.search(
        rf'<form[^>]*action="{re.escape(action)}"[^>]*>(.*?)</form>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _extract_google_oauth_href(html: str) -> str:
    match = re.search(
        r'<a href="([^"]+)" class="btn auth-oauth-btn">',
        html,
    )
    assert match is not None
    return match.group(1)


@pytest.fixture(autouse=True)
def configure_google_oauth() -> None:
    s = main_module.settings
    original_client_id = s.GOOGLE_OAUTH_CLIENT_ID
    original_client_secret = s.GOOGLE_OAUTH_CLIENT_SECRET
    original_redirect_uri = s.GOOGLE_OAUTH_REDIRECT_URI
    s.GOOGLE_OAUTH_CLIENT_ID = "google-client-id"
    s.GOOGLE_OAUTH_CLIENT_SECRET = "google-client-secret"
    s.GOOGLE_OAUTH_REDIRECT_URI = "http://test/auth/google/callback"
    try:
        yield
    finally:
        s.GOOGLE_OAUTH_CLIENT_ID = original_client_id
        s.GOOGLE_OAUTH_CLIENT_SECRET = original_client_secret
        s.GOOGLE_OAUTH_REDIRECT_URI = original_redirect_uri
