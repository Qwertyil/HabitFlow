from __future__ import annotations

import json
import logging

from src.config import Settings
from src.logging_config import (
    JsonEventFormatter,
    TextEventFormatter,
    configure_logging,
    set_request_id,
)


def _settings(**overrides: object) -> Settings:
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
        **overrides,
    )


def _record() -> logging.LogRecord:
    record = logging.LogRecord(
        name="src.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Request completed",
        args=(),
        exc_info=None,
    )
    record.component = "web"
    record.event = "request_completed"
    record.request_id = "req-123"
    return record


def test_text_formatter_outputs_single_line_event_record() -> None:
    formatter = TextEventFormatter()

    rendered = formatter.format(_record())

    assert "\n" not in rendered
    assert "timestamp=" in rendered
    assert "level=INFO" in rendered
    assert "logger=src.test" in rendered
    assert "component=web" in rendered
    assert "event=request_completed" in rendered
    assert "request_id=req-123" in rendered
    assert 'message="Request completed"' in rendered


def test_json_formatter_outputs_single_line_json_record() -> None:
    formatter = JsonEventFormatter()

    rendered = formatter.format(_record())

    assert "\n" not in rendered
    payload = json.loads(rendered)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "src.test"
    assert payload["component"] == "web"
    assert payload["event"] == "request_completed"
    assert payload["request_id"] == "req-123"
    assert payload["message"] == "Request completed"
    assert "timestamp" in payload


def test_json_formatter_includes_custom_extra_fields() -> None:
    formatter = JsonEventFormatter()
    record = _record()
    record.method = "GET"
    record.path = "/healthz/live"
    record.status_code = 200
    record.duration_ms = 4.25
    record.client_ip = "127.0.0.1"

    rendered = formatter.format(record)

    payload = json.loads(rendered)
    assert payload["method"] == "GET"
    assert payload["path"] == "/healthz/live"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 4.25
    assert payload["client_ip"] == "127.0.0.1"


def test_configure_logging_is_reentrant_and_applies_context_filter(
    capsys,
) -> None:
    logger = logging.getLogger("habitflow.test.logging")
    set_request_id("req-456")

    configure_logging(_settings(LOG_FORMAT="json"), component="worker")
    configure_logging(_settings(LOG_FORMAT="json"), component="worker")

    logger.info("Worker started", extra={"event": "worker_started"})
    output = capsys.readouterr().out.strip().splitlines()

    assert len(output) == 1
    payload = json.loads(output[0])
    assert payload["component"] == "worker"
    assert payload["event"] == "worker_started"
    assert payload["request_id"] == "req-456"


def test_configure_logging_sets_operational_logger_levels() -> None:
    settings = _settings(LOG_LEVEL="ERROR", SQL_LOG_LEVEL="INFO")

    configure_logging(settings, component="web")

    assert logging.getLogger("sqlalchemy.engine").level == logging.INFO
    assert logging.getLogger("uvicorn.error").level == logging.ERROR
    assert logging.getLogger("apscheduler").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    assert uvicorn_access_logger.level == logging.WARNING
    assert uvicorn_access_logger.propagate is False
