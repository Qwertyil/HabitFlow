import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from src.utils import get_public_error_message, templates

logger = logging.getLogger(__name__)


def _render_error_response(
    request: Request,
    *,
    status_code: int,
    public_detail: str,
) -> Response:
    if "text/html" in request.headers.get("accept", ""):
        from src.utils import ensure_csrf_token

        is_login_page = request.url.path == "/auth/login"
        primary_url = "/auth/login" if is_login_page else "/"
        primary_text = "К форме входа" if is_login_page else "На главную"
        primary_icon = "fa-right-to-bracket" if is_login_page else "fa-home"

        return templates.TemplateResponse(
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
        )

    return JSONResponse(
        status_code=status_code,
        content={"detail": public_detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        internal_detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        logger.info("HTTP %s: %s", exc.status_code, internal_detail)

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
            return RedirectResponse(
                url=redirect_location,
                status_code=exc.status_code,
                headers=redirect_headers,
            )

        public_detail = get_public_error_message(exc.status_code, exc.detail)
        return _render_error_response(
            request, status_code=exc.status_code, public_detail=public_detail
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)

        public_detail = "Что-то пошло не так. Попробуйте ещё раз позже."
        return _render_error_response(
            request, status_code=500, public_detail=public_detail
        )
