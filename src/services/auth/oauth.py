"""OAuth service for Google OAuth flow and account linking."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

import httpx

from src.config import Settings
from src.exceptions import (
    EmailAlreadyExistsError,
    GoogleOauthError,
    OAuthAuthorizationCodeMissingError,
    OAuthEmailNotVerifiedError,
    OAuthIdentityAlreadyLinkedToAnotherUserError,
    OAuthProviderRejectedError,
    OAuthProviderUnavailableError,
    OAuthStateInvalidError,
    ProviderAccountAlreadyLinkedError,
    UserIsInactiveError,
)
from src.repositories.session_store import RedisSessionStore
from src.schemas.auth import OAuthAccountRead
from src.services.auth.base import AuthBaseService
from src.services.google_oauth import GoogleOauth

if TYPE_CHECKING:
    from src.repositories import AuthRepository
    from src.schemas.auth import AuthUser


@dataclass(frozen=True)
class GoogleOauthStartFlow:
    authorization_url: str
    session_payload: dict[str, str]


@dataclass(frozen=True)
class GoogleOauthLoginResult:
    next_url: str
    session_id: str
    user: "AuthUser"


class OAuthService(AuthBaseService):
    """Сервис для OAuth-аутентификации и привязки аккаунтов."""

    def __init__(
        self,
        *,
        auth_repo: "AuthRepository",
        session_store: "RedisSessionStore | None" = None,
        session_ttl_seconds: int | None = None,
        google_oauth_state_ttl_seconds: int | None = None,
        http_client: "httpx.AsyncClient | None" = None,
        google_oauth_client_factory: "Callable[[], GoogleOauth] | None" = None,
        state_token_provider: "Callable[[], str] | None" = None,
        now_provider: "Callable[[], datetime] | None" = None,
        login_session_creator: "Callable[[UUID], Callable[[], str]] | None" = None,
        auth_settings: Settings | None = None,
    ):
        """Инициализировать OAuth сервис."""
        super().__init__(
            auth_repo=auth_repo,
            session_store=session_store,
            session_ttl_seconds=session_ttl_seconds,
            google_oauth_state_ttl_seconds=google_oauth_state_ttl_seconds,
            auth_settings=auth_settings,
            http_client=http_client,
            google_oauth_client_factory=google_oauth_client_factory,
            state_token_provider=state_token_provider,
            now_provider=now_provider,
        )
        self._login_session_creator = login_session_creator

    def start_google_oauth_login(self, *, next_url: str) -> GoogleOauthStartFlow:
        """Начать поток входа через Google OAuth."""
        state = self._state_token_provider()
        if not state:
            raise ValueError("state_token_provider must return a non-empty state")

        session_payload = {
            "state": state,
            "next": self._normalize_next(next_url),
            "issued_at": self._format_datetime(self._now_provider()),
        }
        authorization_url = self._build_google_oauth_client().get_authorization_url(
            state=state
        )
        return GoogleOauthStartFlow(
            authorization_url=authorization_url,
            session_payload=session_payload,
        )

    async def complete_google_oauth_login(
        self,
        *,
        oauth_session: object,
        provided_state: object,
        provider_error: object,
        code: object,
    ) -> GoogleOauthLoginResult:
        """Завершить поток входа через Google OAuth."""
        next_url = "/"
        expected_state: str | None = None
        issued_at: datetime | None = None
        if isinstance(oauth_session, dict):
            next_url = self._normalize_next(oauth_session.get("next"))
            stored_state = oauth_session.get("state")
            if isinstance(stored_state, str) and stored_state:
                expected_state = stored_state
            issued_at = self._parse_datetime(oauth_session.get("issued_at"))

        now = self._now_provider()
        state_deadline = None
        if issued_at is not None:
            state_deadline = issued_at + timedelta(
                seconds=self._google_oauth_state_ttl_seconds
            )

        if (
            not isinstance(provided_state, str)
            or not provided_state
            or expected_state is None
            or issued_at is None
            or state_deadline is None
            or state_deadline <= now
            or not secrets.compare_digest(expected_state, provided_state)
        ):
            raise OAuthStateInvalidError

        if isinstance(provider_error, str) and provider_error:
            raise OAuthProviderRejectedError

        if not isinstance(code, str) or not code:
            raise OAuthAuthorizationCodeMissingError

        try:
            identity = await self._build_google_oauth_client().authenticate(code)
        except GoogleOauthError as exc:
            raise OAuthProviderUnavailableError from exc

        if not identity.email_verified:
            raise OAuthEmailNotVerifiedError

        user = await self.get_or_create_oauth_user(
            email=str(identity.email),
            provider="google",
            provider_user_id=identity.provider_user_id,
        )

        if self._login_session_creator:
            session_id = self._login_session_creator(user.id)()
        else:
            from src.services.auth.login import LoginService

            login_service = LoginService(
                auth_repo=self.auth_repo,
                session_store=self._session_store,
                session_ttl_seconds=self._session_ttl_seconds,
                google_oauth_state_ttl_seconds=self._google_oauth_state_ttl_seconds,
                auth_settings=self._auth_settings,
                now_provider=self._now_provider,
            )
            session_id = await login_service.create_session(user.id)

        return GoogleOauthLoginResult(
            next_url=next_url,
            session_id=session_id,
            user=user,
        )

    async def get_or_create_oauth_user(
        self,
        *,
        email: str,
        provider: str,
        provider_user_id: str,
    ) -> "AuthUser":
        """
        Вернуть пользователя по OAuth-связке или создать нового.
        Автопривязка к существующему пользователю по email отключена из соображений безопасности.
        """
        normalized_email = email.strip().lower()

        account = await self.auth_repo.get_oauth_account(provider, provider_user_id)
        if account:
            linked_user = await self.auth_repo.get_by_id(account.user_id)
            if linked_user and linked_user.is_active:
                return linked_user
            elif linked_user and not linked_user.is_active:
                raise UserIsInactiveError

        try:
            (
                created_user,
                _,
            ) = await self.auth_repo.create_user_with_oauth_account_idempotent(
                email=normalized_email,
                provider=provider,
                provider_user_id=provider_user_id,
            )
            return created_user
        except (EmailAlreadyExistsError, OAuthIdentityAlreadyLinkedToAnotherUserError):
            raise

    async def create_oauth_account(
        self,
        *,
        user_id: UUID,
        provider: str,
        provider_user_id: str,
        provider_email: str | None = None,
    ) -> OAuthAccountRead:
        """Создать OAuth-аккаунт для существующего пользователя."""
        return await self.auth_repo.create_oauth_account(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
        )

    async def link_oauth_account_for_user(
        self,
        *,
        user_id: UUID,
        provider: str,
        provider_user_id: str,
        provider_email: str | None = None,
    ) -> OAuthAccountRead:
        """Привязать OAuth-аккаунт к уже аутентифицированному пользователю."""
        existing_identity = await self.auth_repo.get_oauth_account(
            provider, provider_user_id
        )
        if existing_identity:
            if existing_identity.user_id != user_id:
                raise OAuthIdentityAlreadyLinkedToAnotherUserError(
                    provider=provider, provider_user_id=provider_user_id
                )
            return existing_identity

        existing_provider_link = await self.auth_repo.get_oauth_account_for_user(
            user_id, provider
        )
        if existing_provider_link:
            if existing_provider_link.provider_user_id != provider_user_id:
                raise ProviderAccountAlreadyLinkedError
            return existing_provider_link

        linked_identity = await self.auth_repo.create_oauth_account_idempotent(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=provider_email,
        )
        if linked_identity.user_id != user_id:
            raise OAuthIdentityAlreadyLinkedToAnotherUserError(
                provider=provider, provider_user_id=provider_user_id
            )
        return linked_identity
