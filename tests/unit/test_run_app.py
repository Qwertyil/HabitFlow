from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest

from src.config import Settings


def _settings() -> Settings:
    return Settings(
        POSTGRES_HOST="127.0.0.1",
        POSTGRES_PORT=5432,
        POSTGRES_USER="habitflow",
        POSTGRES_PASSWORD="secret",
        POSTGRES_DB="habitflow",
        REDIS_HOST="127.0.0.1",
        REDIS_PORT=6379,
        REDIS_PASSWORD="redis-secret",
        REDIS_DB=0,
        ZENQUOTES_API_URL="https://example.test/api/quotes",
        REFILL_INTERVAL_HOURS=6,
        DEBUG=False,
        TESTING=False,
        API_DOCS_ENABLED=False,
        UI_SESSION_SECRET_KEY="test-session-secret",
    )


def test_create_configured_app_bootstraps_shared_logging_before_creating_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_app = importlib.import_module("src.run_app")
    settings = _settings()
    calls: list[tuple[Any, ...]] = []
    app = object()

    def fake_load_settings() -> Settings:
        calls.append(("load_settings", None))
        return settings

    def fake_configure_logging(configured_settings: Settings, component: str) -> None:
        calls.append(("configure_logging", configured_settings, component))

    def fake_create_app(app_settings: Settings) -> object:
        calls.append(("create_app", app_settings))
        return app

    monkeypatch.setattr(run_app, "load_settings", fake_load_settings)
    monkeypatch.setattr(run_app, "configure_logging", fake_configure_logging)
    monkeypatch.setattr(run_app, "create_app", fake_create_app)

    configured_app = run_app.create_configured_app()

    assert configured_app is app
    assert calls == [
        ("load_settings", None),
        ("configure_logging", settings, "web"),
        ("create_app", settings),
    ]


def test_run_app_main_uses_factory_import_string_when_reload_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_app = importlib.import_module("src.run_app")
    calls: list[tuple[Any, ...]] = []

    def fake_uvicorn_run(app: object, **kwargs: object) -> None:
        calls.append(("uvicorn.run", app, kwargs))

    monkeypatch.setattr(run_app.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_PORT", "8123")
    monkeypatch.setenv("UVICORN_RELOAD", "true")
    monkeypatch.setenv("PROXY_HEADERS", "true")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.1")

    run_app.main()

    _, uvicorn_app, uvicorn_kwargs = calls[0]
    assert uvicorn_app == "src.run_app:create_configured_app"
    assert uvicorn_kwargs == {
        "factory": True,
        "host": "0.0.0.0",
        "port": 8123,
        "reload": True,
        "proxy_headers": True,
        "forwarded_allow_ips": "10.0.0.1",
        "log_config": None,
        "access_log": False,
    }


def test_run_app_main_bootstraps_app_directly_when_reload_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_app = importlib.import_module("src.run_app")
    configured_app = object()
    calls: list[tuple[Any, ...]] = []

    def fake_create_configured_app() -> object:
        calls.append(("create_configured_app", None))
        return configured_app

    def fake_uvicorn_run(app: object, **kwargs: object) -> None:
        calls.append(("uvicorn.run", app, kwargs))

    monkeypatch.setattr(run_app, "create_configured_app", fake_create_configured_app)
    monkeypatch.setattr(run_app.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setenv("APP_HOST", "127.0.0.1")
    monkeypatch.setenv("APP_PORT", "9000")
    monkeypatch.setenv("UVICORN_RELOAD", "false")
    monkeypatch.setenv("PROXY_HEADERS", "false")
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_IPS", raising=False)

    run_app.main()

    assert calls[0] == ("create_configured_app", None)
    _, uvicorn_app, uvicorn_kwargs = calls[1]
    assert uvicorn_app is configured_app
    assert uvicorn_kwargs == {
        "host": "127.0.0.1",
        "port": 9000,
        "reload": False,
        "proxy_headers": False,
        "forwarded_allow_ips": "127.0.0.1",
        "log_config": None,
        "access_log": False,
    }


def test_src_main_uses_configured_app_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_app = importlib.import_module("src.run_app")
    app = object()

    def fake_create_configured_app() -> object:
        return app

    monkeypatch.setattr(run_app, "create_configured_app", fake_create_configured_app)
    sys.modules.pop("src.main", None)

    main_module = importlib.import_module("src.main")

    assert main_module.app is app
    sys.modules.pop("src.main", None)
