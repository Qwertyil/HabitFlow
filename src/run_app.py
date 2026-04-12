from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

from src.application import create_app
from src.config import load_settings
from src.logging_config import configure_logging

_TRUTHY_VALUES = {"1", "true", "yes", "on"}


def _env_flag(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default)
    return value.strip().lower() in _TRUTHY_VALUES


def create_configured_app() -> FastAPI:
    settings = load_settings()
    configure_logging(settings, component="web")
    return create_app(settings)


def main() -> None:
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))
    reload_enabled = _env_flag("UVICORN_RELOAD", os.getenv("DEBUG", "false"))
    proxy_headers = _env_flag("PROXY_HEADERS")
    forwarded_allow_ips = os.getenv(
        "FORWARDED_ALLOW_IPS",
        os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1"),
    )

    if reload_enabled:
        uvicorn.run(
            "src.run_app:create_configured_app",
            factory=True,
            host=host,
            port=port,
            reload=True,
            proxy_headers=proxy_headers,
            forwarded_allow_ips=forwarded_allow_ips,
            log_config=None,
            access_log=False,
        )
        return

    uvicorn.run(
        create_configured_app(),
        host=host,
        port=port,
        reload=False,
        proxy_headers=proxy_headers,
        forwarded_allow_ips=forwarded_allow_ips,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
