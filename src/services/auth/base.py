"""Base auth service with shared functionality."""

import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import httpx
from argon2 import PasswordHasher

from src.config import Settings
from src.repositories import AuthRepository
from src.repositories.session_store import RedisSessionStore
from src.schemas.auth import AuthUser
from src.services.google_oauth import GoogleOauth


class AuthBaseService:
    """Базовый класс для сервисов авторизации с общим функционалом."""

    _ph = PasswordHasher()
    _SESSION_STORE_NOT_CONFIGURED: Final[str] = (
        "Session store is not configured for auth sessions"
    )

    @property
    def ph(self) -> PasswordHasher:
        return self._ph

    @ph.setter
    def ph(self, value: PasswordHasher) -> None:
        self._ph = value

    def __init__(
        self,
        auth_repo: AuthRepository,
        session_store: RedisSessionStore | None = None,
        session_ttl_seconds: int | None = None,
        google_oauth_state_ttl_seconds: int | None = None,
        auth_settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        google_oauth_client_factory: Callable[[], GoogleOauth] | None = None,
        state_token_provider: Callable[[], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        """Инициализировать базовый сервис авторизации."""
        if auth_settings is None:
            from src.config import settings as runtime_settings

            auth_settings = runtime_settings

        resolved_session_ttl = (
            session_ttl_seconds
            if session_ttl_seconds is not None
            else auth_settings.AUTH_SESSION_MAX_AGE
        )
        resolved_oauth_state_ttl = (
            google_oauth_state_ttl_seconds
            if google_oauth_state_ttl_seconds is not None
            else auth_settings.GOOGLE_OAUTH_STATE_TTL
        )

        self._auth_settings = auth_settings
        self.auth_repo = auth_repo
        self._session_store = session_store
        self._session_ttl_seconds = resolved_session_ttl
        self._google_oauth_state_ttl_seconds = resolved_oauth_state_ttl
        self._http_client = http_client
        self._google_oauth_client_factory = google_oauth_client_factory
        self._state_token_provider = state_token_provider or (
            lambda: secrets.token_urlsafe(32)
        )
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        return (
            value.astimezone(UTC)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _normalize_next(next_value: object) -> str:
        if not isinstance(next_value, str) or not next_value:
            return "/"

        from urllib.parse import urlsplit

        parsed = urlsplit(next_value)
        if parsed.scheme or parsed.netloc:
            return "/"
        if not next_value.startswith("/") or next_value.startswith("//"):
            return "/"
        return next_value

    def _require_session_store(self) -> RedisSessionStore:
        if self._session_store is None:
            raise RuntimeError(self._SESSION_STORE_NOT_CONFIGURED)
        return self._session_store

    def _build_google_oauth_client(self) -> GoogleOauth:
        if self._google_oauth_client_factory is not None:
            return self._google_oauth_client_factory()

        if not self._auth_settings.google_oauth_enabled:
            from src.exceptions import OAuthConfigurationError

            raise OAuthConfigurationError("Google OAuth is not configured")
        return GoogleOauth(
            client_id=str(self._auth_settings.GOOGLE_OAUTH_CLIENT_ID),
            client_secret=str(self._auth_settings.GOOGLE_OAUTH_CLIENT_SECRET),
            redirect_uri=str(self._auth_settings.GOOGLE_OAUTH_REDIRECT_URI),
            http_client=self._http_client,
        )

    def hash_password(self, password: str) -> str:
        """Хешировать пароль."""
        return self.ph.hash(password)

    def verify_password(self, password: str, hash: str) -> bool:
        """Проверить пароль против хеша."""
        from argon2.exceptions import InvalidHashError, VerificationError

        try:
            return self.ph.verify(hash, password)
        except (VerificationError, InvalidHashError):
            return False

    async def get_user(self, user_id: UUID) -> AuthUser | None:
        """Получить пользователя по идентификатору."""
        return await self.auth_repo.get_by_id(user_id)
