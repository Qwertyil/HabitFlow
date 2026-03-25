from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.database.models import OAuthAccount, User
from src.exceptions import (
    EmailAlreadyExistsError,
    OAuthIdentityAlreadyLinkedToAnotherUserError,
)
from src.schemas.auth import (
    AuthUser,
    AuthUserWithPasswordField,
    OAuthAccountRead,
    UserCreate,
    UserUpdate,
)

from .base import GenericSqlRepository


class AuthRepository(
    GenericSqlRepository[UserCreate, AuthUser, UserUpdate, User, UUID]
):
    _model = User
    _create_schema = UserCreate
    _read_schema = AuthUser
    _update_schema = UserUpdate

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()

    # Second convert method (first one in base repo) because we are working with 2 tables in this repo - User and OAuth
    @staticmethod
    def _convert_oauth_model_to_read(record: OAuthAccount) -> OAuthAccountRead:
        return OAuthAccountRead.model_validate(record, from_attributes=True)

    async def get_user_by_email(self, email: str) -> AuthUserWithPasswordField | None:
        normalized = self._normalize_email(email)
        stmt = select(User).where(func.lower(User.email) == normalized)
        result = await self._session.execute(stmt)
        user = result.scalars().first()
        if not user:
            return None
        return AuthUserWithPasswordField.model_validate(user)

    async def create_user(self, email: str, password_hash: str | None) -> AuthUser:
        return await self.add(
            UserCreate(
                email=self._normalize_email(email),
                password_hash=password_hash,
                is_active=True,
            )
        )

    async def set_user_password(
        self, user_id: UUID, password_hash: str
    ) -> AuthUser | None:
        return await self.update(
            user_id,
            UserUpdate(password_hash=password_hash),
        )

    async def set_user_active(self, user_id: UUID, is_active: bool) -> AuthUser | None:
        return await self.update(
            user_id,
            UserUpdate(is_active=is_active),
        )

    async def create_oauth_account(
        self,
        *,
        user_id: UUID,
        provider: str,
        provider_user_id: str,
        provider_email: str | None = None,
    ) -> OAuthAccountRead:
        account = OAuthAccount(
            user_id=user_id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=self._normalize_email(provider_email)
            if provider_email
            else None,
        )
        self._session.add(account)
        await self._session.flush()
        return self._convert_oauth_model_to_read(account)

    async def create_user_with_oauth_account(
        self,
        *,
        email: str,
        provider: str,
        provider_user_id: str,
    ) -> tuple[AuthUser, OAuthAccountRead]:
        user = User(
            email=self._normalize_email(email),
            password_hash=None,
            is_active=True,
        )
        self._session.add(user)
        await self._session.flush()
        oauth_account = await self.create_oauth_account(
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=cast(str | None, user.email),
        )
        return (self._convert_model_to_read(user), oauth_account)

    async def create_user_with_oauth_account_idempotent(
        self,
        *,
        email: str,
        provider: str,
        provider_user_id: str,
    ) -> tuple[AuthUser, OAuthAccountRead]:
        normalized_email = email.strip().lower()

        try:
            async with self._session.begin_nested():
                return await self.create_user_with_oauth_account(
                    email=normalized_email,
                    provider=provider,
                    provider_user_id=provider_user_id,
                )

        except IntegrityError as exc:
            existing_identity = await self.get_oauth_account(provider, provider_user_id)
            if existing_identity:
                linked_user = await self._session.get(User, existing_identity.user_id)
                if not linked_user:
                    raise

                actual_email = linked_user.email.strip().lower()
                if actual_email != normalized_email:
                    raise OAuthIdentityAlreadyLinkedToAnotherUserError(
                        provider=provider, provider_user_id=provider_user_id
                    ) from exc

                return self._convert_model_to_read(linked_user), existing_identity

            existing_user = await self.get_user_by_email(normalized_email)
            if existing_user:
                raise EmailAlreadyExistsError from exc

            raise

    async def create_oauth_account_idempotent(
        self,
        *,
        user_id: UUID,
        provider: str,
        provider_user_id: str,
        provider_email: str | None = None,
    ) -> OAuthAccountRead:
        try:
            async with self._session.begin_nested():
                return await self.create_oauth_account(
                    user_id=user_id,
                    provider=provider,
                    provider_user_id=provider_user_id,
                    provider_email=provider_email,
                )
        except IntegrityError:
            existing_identity = await self.get_oauth_account(provider, provider_user_id)
            if existing_identity:
                return existing_identity
            raise

    async def get_oauth_account(
        self,
        provider: str,
        provider_user_id: str,
    ) -> OAuthAccountRead | None:
        stmt = select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
        result = await self._session.execute(stmt)
        account = result.scalars().first()
        if not account:
            return None
        return self._convert_oauth_model_to_read(account)

    async def get_oauth_account_for_user(
        self,
        user_id: UUID,
        provider: str,
    ) -> OAuthAccountRead | None:
        stmt = select(OAuthAccount).where(
            OAuthAccount.user_id == user_id,
            OAuthAccount.provider == provider,
        )
        result = await self._session.execute(stmt)
        account = result.scalars().first()
        if not account:
            return None
        return self._convert_oauth_model_to_read(account)
