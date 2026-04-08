"""Login service for authentication and session management."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import httpx

from src.config import Settings
from src.repositories import AuthRepository
from src.repositories.session_store import RedisSessionStore
from src.schemas.auth import AuthLogin, AuthUser
from src.services.auth.base import AuthBaseService
from src.services.google_oauth import GoogleOauth


class LoginService(AuthBaseService):
    """Сервис для аутентификации пользователей и управления сессиями."""

    def __init__(
        self,
        *,
        auth_repo: AuthRepository,
        auth_settings: Settings,
        session_store: RedisSessionStore | None = None,
        session_ttl_seconds: int | None = None,
        google_oauth_state_ttl_seconds: int | None = None,
        http_client: httpx.AsyncClient | None = None,
        google_oauth_client_factory: Callable[[], GoogleOauth] | None = None,
        state_token_provider: Callable[[], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ):
        """Инициализировать Login сервис."""
        super().__init__(
            auth_repo=auth_repo,
            auth_settings=auth_settings,
            session_store=session_store,
            session_ttl_seconds=session_ttl_seconds,
            google_oauth_state_ttl_seconds=google_oauth_state_ttl_seconds,
            http_client=http_client,
            google_oauth_client_factory=google_oauth_client_factory,
            state_token_provider=state_token_provider,
            now_provider=now_provider,
        )

    async def authenticate(self, payload: AuthLogin) -> AuthUser | None:
        """Проверить логин/пароль и вернуть пользователя при успехе."""
        user = await self.auth_repo.get_user_by_email(payload.email)
        if not user or not user.is_active or not user.password_hash:
            return None
        if not await self.verify_password_async(payload.password, user.password_hash):
            return None
        return AuthUser.model_validate(user)

    async def create_session(self, user_id: UUID) -> str:
        """Создать auth-сессию и вернуть её идентификатор."""
        store = self._require_session_store()
        if self._session_ttl_seconds <= 0:
            raise ValueError("session_ttl_seconds must be greater than zero")

        created_at = self._now_provider()
        expires_at = created_at + timedelta(seconds=self._session_ttl_seconds)
        session_id = str(uuid4())
        await store.create_session(
            session_id=session_id,
            user_id=user_id,
            payload={
                "created_at": self._format_datetime(created_at),
                "expires_at": self._format_datetime(expires_at),
            },
            ttl_seconds=self._session_ttl_seconds,
        )
        return session_id

    async def logout(self, session_id: str, user_id: UUID) -> None:
        """Завершить одну auth-сессию пользователя, если она ему принадлежит."""
        store = self._require_session_store()
        session_payload = await store.get_session(session_id=session_id)
        if session_payload is None:
            return

        payload_user_id = session_payload.get("user_id")
        if not isinstance(payload_user_id, str):
            await store.delete_session(session_id=session_id)
            return

        try:
            session_user_id = UUID(payload_user_id)
        except ValueError:
            await store.delete_session(session_id=session_id)
            return

        if session_user_id != user_id:
            return

        await store.delete_session(session_id=session_id)

    async def logout_all(self, user_id: UUID) -> None:
        """Завершить все auth-сессии пользователя."""
        store = self._require_session_store()
        await store.delete_user_sessions(user_id=user_id)

    async def resolve_user(self, session_id: str) -> AuthUser | None:
        """Разрешить пользователя по session_id или вернуть None."""
        store = self._require_session_store()
        session_payload = await store.get_session(session_id=session_id)
        if session_payload is None:
            return None

        if session_payload.get("revoked") or session_payload.get("revoked_at"):
            await store.delete_session(session_id=session_id)
            return None

        expires_at = self._parse_datetime(session_payload.get("expires_at"))
        now = self._now_provider()
        if expires_at is not None and expires_at <= now:
            await store.delete_session(session_id=session_id)
            return None

        user_id_raw = session_payload.get("user_id")
        if not isinstance(user_id_raw, str):
            await store.delete_session(session_id=session_id)
            return None

        try:
            user_id = UUID(user_id_raw)
        except ValueError:
            await store.delete_session(session_id=session_id)
            return None

        user = await self.auth_repo.get_by_id(user_id)
        if user is None or not user.is_active:
            await store.delete_session(session_id=session_id)
            return None
        return user
