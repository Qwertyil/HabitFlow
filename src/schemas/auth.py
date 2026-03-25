from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator

from .base import InDBBase


class EmailNormalizedModel(BaseModel):
    @field_validator("email", mode="before", check_fields=False)
    @classmethod
    def normalize_email(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class AuthCredentials(EmailNormalizedModel):
    email: EmailStr
    password: str


class AuthRegister(AuthCredentials):
    @field_validator("password")
    @classmethod
    def validate_password_length(cls, value: str) -> str:
        if len(value) < 8 or len(value) > 256:
            raise ValueError("password must be between 8 and 256 characters")
        return value


class AuthLogin(AuthCredentials):
    pass


class UserCreate(EmailNormalizedModel):
    email: EmailStr
    password_hash: str | None = None
    is_active: bool = True


class UserUpdate(EmailNormalizedModel):
    email: EmailStr | None = None
    password_hash: str | None = None
    is_active: bool | None = None


class AuthUser(InDBBase):
    email: EmailStr
    is_active: bool


class AuthUserWithPasswordField(AuthUser):
    password_hash: str | None


class OAuthAccountRead(InDBBase):
    user_id: UUID
    provider: str
    provider_user_id: str
    provider_email: EmailStr | None = None
