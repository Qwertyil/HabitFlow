import logging
import os
import secrets
from functools import cached_property
from typing import ClassVar, Literal
from urllib.parse import quote

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE = ".env"
_LOG_FORMATS = {"json", "text"}


def _quote_url_part(value: str | None) -> str:
    return quote(value or "", safe="")


class Settings(BaseSettings):
    _VALID_LOG_LEVELS: ClassVar[set[str]] = set(logging.getLevelNamesMapping())

    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str

    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str
    REDIS_DB: int

    UI_SESSION_SECRET_KEY: str | None = None
    UI_SESSION_COOKIE_NAME: str = "habitflow_session"
    UI_SESSION_MAX_AGE: int = 60 * 60 * 24 * 14  # 14 days
    UI_SESSION_SAME_SITE: Literal["lax", "strict", "none"] = "lax"
    UI_SESSION_HTTPS_ONLY: bool = False

    AUTH_SESSION_COOKIE_NAME: str = "auth_session"
    AUTH_SESSION_MAX_AGE: int = 60 * 60 * 24 * 14  # 14 days
    AUTH_SESSION_SAME_SITE: Literal["lax", "strict", "none"] = "lax"
    AUTH_SESSION_HTTPS_ONLY: bool = False

    GOOGLE_OAUTH_CLIENT_ID: str | None = None
    GOOGLE_OAUTH_CLIENT_SECRET: str | None = None
    GOOGLE_OAUTH_REDIRECT_URI: str | None = None
    GOOGLE_OAUTH_STATE_TTL: int = 10 * 60  # 10 minutes

    ZENQUOTES_API_URL: str
    REFILL_INTERVAL_HOURS: int

    DEBUG: bool = False
    TESTING: bool = False
    API_DOCS_ENABLED: bool = False

    LOG_LEVEL: str | None = None
    LOG_FORMAT: Literal["text", "json"] = "text"
    REQUEST_ID_HEADER: str = "X-Request-ID"
    SQL_LOG_LEVEL: str = "WARNING"

    @field_validator("LOG_LEVEL", "SQL_LOG_LEVEL", mode="before")
    @classmethod
    def normalize_log_level(cls, value: object) -> str | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped.upper() if stripped else None
        return str(value).upper()

    @field_validator("LOG_LEVEL", "SQL_LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        if value not in cls._VALID_LOG_LEVELS:
            allowed = ", ".join(sorted(cls._VALID_LOG_LEVELS))
            msg = f"Invalid {info.field_name}={value!r}; allowed: {allowed}"
            raise ValueError(msg)
        return value

    @field_validator("LOG_FORMAT", mode="before")
    @classmethod
    def normalize_log_format(cls, value: object) -> str:
        normalized = str(value).strip().lower()
        if normalized not in _LOG_FORMATS:
            allowed = ", ".join(sorted(_LOG_FORMATS))
            msg = f"Invalid LOG_FORMAT={value!r}; allowed: {allowed}"
            raise ValueError(msg)
        return normalized

    @field_validator("REQUEST_ID_HEADER", mode="before")
    @classmethod
    def validate_request_id_header(cls, value: object) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("REQUEST_ID_HEADER must not be empty")
        return normalized

    @property
    def logging_level(self) -> int:
        """Уровень логирования root logger: LOG_LEVEL из env или DEBUG/INFO по флагу DEBUG."""
        return logging.getLevelNamesMapping()[self.default_log_level_name]

    @property
    def default_log_level_name(self) -> str:
        return (
            self.LOG_LEVEL
            if self.LOG_LEVEL is not None
            else ("DEBUG" if self.DEBUG else "INFO")
        )

    @property
    def sql_logging_level(self) -> int:
        return logging.getLevelNamesMapping()[self.SQL_LOG_LEVEL]

    @property
    def google_oauth_enabled(self) -> bool:
        return bool(
            self.GOOGLE_OAUTH_CLIENT_ID
            and self.GOOGLE_OAUTH_CLIENT_SECRET
            and self.GOOGLE_OAUTH_REDIRECT_URI
        )

    @property
    def _postgres_auth(self) -> str:
        user = _quote_url_part(self.POSTGRES_USER)
        password = _quote_url_part(self.POSTGRES_PASSWORD)
        return f"{user}:{password}"

    def _build_postgres_url(self, driver: str) -> str:
        return (
            f"postgresql+{driver}://"
            f"{self._postgres_auth}@"
            f"{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/"
            f"{self.POSTGRES_DB}"
        )

    @property
    def DATABASE_URL_asyncpg(self) -> str:
        return self._build_postgres_url("asyncpg")

    @property
    def DATABASE_URL_psycopg2(self) -> str:
        return self._build_postgres_url("psycopg2")

    @property
    def redis_dsn(self) -> str:
        auth = ""
        if self.REDIS_PASSWORD:
            auth = f":{_quote_url_part(self.REDIS_PASSWORD)}@"

        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @cached_property
    def session_secret_key(self) -> str:
        if self.UI_SESSION_SECRET_KEY:
            return self.UI_SESSION_SECRET_KEY
        if not self.DEBUG:
            raise ValueError("UI_SESSION_SECRET_KEY must be set when DEBUG=False")
        return secrets.token_urlsafe(32)

    model_config = SettingsConfigDict(env_file=DEFAULT_ENV_FILE, extra="ignore")


def load_settings() -> Settings:
    """
    Собрать настройки из окружения (без кэша; один вызов на процесс/инстанс приложения).

    Путь к dotenv задаётся только переменной окружения ENV_FILE (не из самого .env),
    чтобы можно было поднимать инстансы с разными файлами, например ``ENV_FILE=.env.prod``.
    """
    env_file = os.environ.get("ENV_FILE", DEFAULT_ENV_FILE)
    return Settings(_env_file=env_file)
