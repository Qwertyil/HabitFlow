from __future__ import annotations

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from src.config import Settings

_request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    return _request_id_context.get()


def set_request_id(request_id: str | None) -> None:
    _request_id_context.set(request_id)


class ContextFilter(logging.Filter):
    def __init__(self, *, component: str) -> None:
        super().__init__()
        self.component = component

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = self.component
        request_id = getattr(record, "request_id", None) or get_request_id()
        if request_id:
            record.request_id = request_id
        return True


class BaseEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        return self.render(self.build_payload(record))

    def build_payload(self, record: logging.LogRecord) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "component": getattr(record, "component", ""),
            "event": getattr(
                record,
                "event",
                record.msg if isinstance(record.msg, str) else "log",
            ),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        if record.message:
            payload["message"] = record.message
        return payload

    def render(self, payload: dict[str, Any]) -> str:
        raise NotImplementedError


class TextEventFormatter(BaseEventFormatter):
    def render(self, payload: dict[str, Any]) -> str:
        return " ".join(
            f"{key}={self._stringify(value)}" for key, value in payload.items()
        )

    def _stringify(self, value: object) -> str:
        text = str(value).replace("\n", "\\n")
        needs_quotes = any(char.isspace() for char in text) or "=" in text
        return json.dumps(text) if needs_quotes else text


class JsonEventFormatter(BaseEventFormatter):
    def render(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_logging(settings: Settings, component: str) -> None:
    formatter_name = f"{settings.LOG_FORMAT}_event"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "context": {
                    "()": ContextFilter,
                    "component": component,
                }
            },
            "formatters": {
                "text_event": {"()": TextEventFormatter},
                "json_event": {"()": JsonEventFormatter},
            },
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": formatter_name,
                    "filters": ["context"],
                }
            },
            "root": {
                "handlers": ["stdout"],
                "level": settings.default_log_level_name,
            },
        }
    )
