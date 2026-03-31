"""Registration service for user management."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

import httpx
from sqlalchemy.exc import IntegrityError

from src.config import Settings
from src.exceptions import EmailAlreadyExistsError
from src.repositories import AuthRepository
from src.repositories.session_store import RedisSessionStore
from src.schemas.auth import AuthRegister, AuthUser
from src.services.auth.base import AuthBaseService
from src.services.google_oauth import GoogleOauth


class RegistrationService(AuthBaseService):
    """Сервис для регистрации и управления пользователями."""

    def __init__(
        self,
        *,
        auth_repo: AuthRepository,
        session_store: RedisSessionStore | None = None,
        session_ttl_seconds: int | None = None,
        google_oauth_state_ttl_seconds: int | None = None,
        http_client: httpx.AsyncClient | None = None,
        google_oauth_client_factory: Callable[[], GoogleOauth] | None = None,
        state_token_provider: Callable[[], str] | None = None,
        now_provider: Callable[[], datetime] | None = None,
        auth_settings: Settings | None = None,
    ):
        """Инициализировать Registration сервис."""
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

    async def register(self, payload: AuthRegister) -> AuthUser:
        """Зарегистрировать пользователя по email/паролю."""
        existing = await self.auth_repo.get_user_by_email(payload.email)
        if existing:
            raise EmailAlreadyExistsError

        try:
            return await self.auth_repo.create_user(
                payload.email,
                self.hash_password(payload.password),
            )
        except IntegrityError as exc:
            raise EmailAlreadyExistsError from exc

    async def set_password(self, user_id: UUID, password: str) -> AuthUser | None:
        """Обновить пароль пользователя."""
        validated_password = AuthRegister.validate_password_length(password)
        return await self.auth_repo.set_user_password(
            user_id, self.hash_password(validated_password)
        )

    async def set_user_active(self, user_id: UUID, is_active: bool) -> AuthUser | None:
        """Изменить статус активности пользователя."""
        return await self.auth_repo.set_user_active(user_id, is_active)
