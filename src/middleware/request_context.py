from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.routing import BaseRoute

from src.logging_config import reset_request_id, set_request_id

logger = logging.getLogger("src.middleware.request_context")
_HEALTH_ROUTE_PREFIX = "/healthz"


def _resolve_request_id(request: Request, *, header_name: str) -> str:
    incoming = request.headers.get(header_name)
    if incoming:
        return incoming
    return str(uuid4())


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route, BaseRoute) and isinstance(route_path, str):
        return route_path
    return request.url.path


def _client_ip(request: Request) -> str | None:
    client = request.client
    if client is None:
        return None
    return client.host


def _log_level_for_request(*, path: str, status_code: int) -> int:
    if status_code < 400 and path.startswith(_HEALTH_ROUTE_PREFIX):
        return logging.DEBUG
    return logging.INFO


def register_request_context_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_context(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        settings = request.app.state.settings
        request_id = _resolve_request_id(
            request, header_name=settings.REQUEST_ID_HEADER
        )
        request.state.request_id = request_id
        request_id_token = set_request_id(request_id)
        start_time = perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception:
                duration_ms = round((perf_counter() - start_time) * 1000, 2)
                path = _route_template(request)
                logger.log(
                    _log_level_for_request(path=path, status_code=500),
                    "HTTP request completed",
                    extra={
                        "event": "http_request_completed",
                        "method": request.method,
                        "path": path,
                        "status_code": 500,
                        "duration_ms": duration_ms,
                        "client_ip": _client_ip(request),
                        "request_id": request_id,
                    },
                )
                raise

            response.headers[settings.REQUEST_ID_HEADER] = request_id
            duration_ms = round((perf_counter() - start_time) * 1000, 2)
            path = _route_template(request)
            logger.log(
                _log_level_for_request(path=path, status_code=response.status_code),
                "HTTP request completed",
                extra={
                    "event": "http_request_completed",
                    "method": request.method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "client_ip": _client_ip(request),
                    "request_id": request_id,
                },
            )
            return response
        finally:
            reset_request_id(request_id_token)
