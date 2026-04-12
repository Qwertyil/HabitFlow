from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import logging
import pytest

from src.config import Settings, load_settings

SETTINGS_KEYS = (
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "REDIS_HOST",
    "REDIS_PORT",
    "REDIS_PASSWORD",
    "REDIS_DB",
    "ZENQUOTES_API_URL",
    "REFILL_INTERVAL_HOURS",
    "DEBUG",
    "TESTING",
    "API_DOCS_ENABLED",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "REQUEST_ID_HEADER",
    "SQL_LOG_LEVEL",
    "UI_SESSION_SECRET_KEY",
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_OAUTH_REDIRECT_URI",
)


def _write_env_file(path: Path, *, postgres_port: int) -> None:
    path.write_text(
        dedent(
            f"""\
            POSTGRES_HOST=127.0.0.1
            POSTGRES_PORT={postgres_port}
            POSTGRES_USER=habitflow
            POSTGRES_PASSWORD=secret
            POSTGRES_DB=habitflow
            REDIS_HOST=127.0.0.1
            REDIS_PORT=6379
            REDIS_PASSWORD=redis-secret
            REDIS_DB=0
            ZENQUOTES_API_URL=https://example.test/api/quotes
            REFILL_INTERVAL_HOURS=1
            DEBUG=true
            TESTING=false
            API_DOCS_ENABLED=false
            UI_SESSION_SECRET_KEY=test-session-secret
            """
        ),
        encoding="utf-8",
    )


def _clear_settings_env(monkeypatch) -> None:  # noqa: ANN001
    for key in SETTINGS_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("ENV_FILE", raising=False)


def test_load_settings_uses_env_file_from_environment_variable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    selected_env_file = tmp_path / ".env.test"
    _write_env_file(selected_env_file, postgres_port=6432)
    monkeypatch.setenv("ENV_FILE", str(selected_env_file))

    settings = load_settings()

    assert settings.POSTGRES_PORT == 6432


def test_load_settings_does_not_switch_dotenv_from_value_inside_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_settings_env(monkeypatch)
    default_env_file = tmp_path / ".env"
    selected_env_file = tmp_path / ".env.prod"
    _write_env_file(selected_env_file, postgres_port=7432)
    default_env_file.write_text(
        dedent(
            """\
            ENV_FILE=.env.prod
            POSTGRES_HOST=127.0.0.1
            POSTGRES_PORT=5432
            POSTGRES_USER=habitflow
            POSTGRES_PASSWORD=secret
            POSTGRES_DB=habitflow
            REDIS_HOST=127.0.0.1
            REDIS_PORT=6379
            REDIS_PASSWORD=redis-secret
            REDIS_DB=0
            ZENQUOTES_API_URL=https://example.test/api/quotes
            REFILL_INTERVAL_HOURS=1
            DEBUG=true
            TESTING=false
            API_DOCS_ENABLED=false
            UI_SESSION_SECRET_KEY=test-session-secret
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.POSTGRES_PORT == 5432


def _base_settings_kwargs() -> dict[str, object]:
    return {
        "POSTGRES_HOST": "127.0.0.1",
        "POSTGRES_PORT": 5432,
        "POSTGRES_USER": "habitflow",
        "POSTGRES_PASSWORD": "secret",
        "POSTGRES_DB": "habitflow",
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": 6379,
        "REDIS_PASSWORD": "redis-secret",
        "REDIS_DB": 0,
        "ZENQUOTES_API_URL": "https://example.test/api/quotes",
        "REFILL_INTERVAL_HOURS": 1,
        "DEBUG": False,
        "TESTING": False,
        "API_DOCS_ENABLED": False,
        "UI_SESSION_SECRET_KEY": "test-session-secret",
    }


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("LOG_LEVEL", "verbose"),
        ("SQL_LOG_LEVEL", "chatty"),
        ("LOG_FORMAT", "pretty"),
        ("REQUEST_ID_HEADER", "   "),
    ],
)
def test_settings_reject_invalid_logging_values(
    field_name: str,
    value: object,
) -> None:
    kwargs = _base_settings_kwargs()
    kwargs[field_name] = value

    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_settings_normalize_logging_configuration_values() -> None:
    settings = Settings(
        **_base_settings_kwargs(),
        LOG_LEVEL=" warning ",
        LOG_FORMAT=" JSON ",
        REQUEST_ID_HEADER=" X-Correlation-ID ",
        SQL_LOG_LEVEL=" error ",
    )

    assert settings.LOG_LEVEL == "WARNING"
    assert settings.LOG_FORMAT == "json"
    assert settings.REQUEST_ID_HEADER == "X-Correlation-ID"
    assert settings.SQL_LOG_LEVEL == "ERROR"


def test_settings_default_log_level_uses_debug_when_log_level_missing() -> None:
    kwargs = _base_settings_kwargs()
    kwargs["DEBUG"] = True
    settings = Settings(**kwargs)

    assert settings.default_log_level_name == "DEBUG"
    assert settings.logging_level == logging.DEBUG


def test_settings_use_documented_logging_defaults() -> None:
    settings = Settings(**_base_settings_kwargs())

    assert settings.LOG_FORMAT == "text"
    assert settings.REQUEST_ID_HEADER == "X-Request-ID"
    assert settings.SQL_LOG_LEVEL == "WARNING"
    assert settings.default_log_level_name == "INFO"
