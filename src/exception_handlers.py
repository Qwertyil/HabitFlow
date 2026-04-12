import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from src.web import templates

logger = logging.getLogger(__name__)


PUBLIC_ERRORS = {
    400: "Некорректный запрос.",
    401: "Необходимо войти в систему.",
    403: "У вас нет доступа к этой странице.",
    404: "Страница не найдена.",
    405: "Метод запроса не поддерживается.",
    408: "Время ожидания ответа истекло.",
    409: "Конфликт данных.",
    422: "Некорректно заполнены данные.",
    429: "Слишком много запросов. Попробуйте позже.",
    500: "Что-то пошло не так. Попробуйте ещё раз позже.",
    502: "Сервис временно недоступен.",
    503: "Сервис временно недоступен.",
    504: "Сервис не ответил вовремя.",
}


def get_public_error_message(status_code: int, detail: object = None) -> str:
    if status_code in PUBLIC_ERRORS:
        return PUBLIC_ERRORS[status_code]

    if 400 <= status_code < 500:
        return "Ошибка запроса."

    return "Что-то пошло не так. Попробуйте ещё раз позже."


def _render_error_response(
    request: Request,
    *,
    status_code: int,
    public_detail: str,
) -> Response:
    if "text/html" in request.headers.get("accept", ""):
        from src.csrf import ensure_csrf_token

        is_login_page = request.url.path == "/auth/login"
        primary_url = "/auth/login" if is_login_page else "/"
        primary_text = "К форме входа" if is_login_page else "На главную"
        primary_icon = "fa-right-to-bracket" if is_login_page else "fa-home"

        return _attach_request_id_header(
            request,
            templates.TemplateResponse(
                request,
                "message.html",
                {
                    "request": request,
                    "current_user": None,
                    "current_user_display_name": None,
                    "title": "Ошибка",
                    "message": public_detail,
                    "message_type": "error",
                    "primary_url": primary_url,
                    "primary_text": primary_text,
                    "primary_icon": primary_icon,
                    "hide_sidebar": True,
                    "csrf_token": ensure_csrf_token(request),
                },
                status_code=status_code,
            ),
        )

    return _attach_request_id_header(
        request,
        JSONResponse(
            status_code=status_code,
            content={"detail": public_detail},
        ),
    )


def _attach_request_id_header(request: Request, response: Response) -> Response:
    request_id = getattr(request.state, "request_id", None)
    if not request_id:
        return response

    header_name = request.app.state.settings.REQUEST_ID_HEADER
    response.headers[header_name] = request_id
    return response


def _request_id_from_request(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        internal_detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        logger.info(
            "HTTP %s: %s",
            exc.status_code,
            internal_detail,
            extra={
                "event": "http_exception_handled",
                "request_id": _request_id_from_request(request),
                "method": request.method,
                "path": request.url.path,
                "status_code": exc.status_code,
            },
        )

        headers = exc.headers or {}
        redirect_location = None
        if headers:
            for header_name, header_value in headers.items():
                if header_name.lower() == "location":
                    redirect_location = header_value
                    break

        if redirect_location is not None and 300 <= exc.status_code < 400:
            redirect_headers = {
                header_name: header_value
                for header_name, header_value in headers.items()
                if header_name.lower() != "location"
            }
            return _attach_request_id_header(
                request,
                RedirectResponse(
                    url=redirect_location,
                    status_code=exc.status_code,
                    headers=redirect_headers,
                ),
            )

        public_detail = get_public_error_message(exc.status_code, exc.detail)
        return _render_error_response(
            request, status_code=exc.status_code, public_detail=public_detail
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        logger.exception(
            "Unhandled error on %s %s",
            request.method,
            request.url.path,
            extra={
                "event": "unhandled_exception",
                "request_id": _request_id_from_request(request),
                "method": request.method,
                "path": request.url.path,
            },
        )

        public_detail = "Что-то пошло не так. Попробуйте ещё раз позже."
        return _render_error_response(
            request, status_code=500, public_detail=public_detail
        )
