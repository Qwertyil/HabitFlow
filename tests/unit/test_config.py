from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from src.config import load_settings

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
