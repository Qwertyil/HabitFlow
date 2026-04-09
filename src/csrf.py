import secrets

from fastapi import HTTPException, Request, status

_JSON_CONTENT_TYPE = "application/json"
_FORM_CONTENT_TYPES = {
    "application/x-www-form-urlencoded",
    "multipart/form-data",
}
_CSRF_HEADER_NAMES = ("x-csrftoken", "x-csrf-token")
_CSRF_ERROR_MESSAGE = (
    "Сессия формы истекла или стала недействительной. "
    "Обновите страницу и попробуйте снова."
)


def csrf_error_message() -> str:
    return _CSRF_ERROR_MESSAGE


def validate_csrf(request: Request, submitted_token: object) -> None:
    expected_token = request.session.get("csrf_token")
    if not isinstance(expected_token, str) or not expected_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token is missing",
        )

    if not isinstance(submitted_token, str) or not secrets.compare_digest(
        expected_token,
        submitted_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )


async def read_request_payload(request: Request) -> tuple[str, dict[str, object]]:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()

    if media_type == _JSON_CONTENT_TYPE:
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Malformed JSON body",
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="JSON body must be an object",
            )
        return "json", payload

    if media_type in _FORM_CONTENT_TYPES:
        form = await request.form()
        raw = dict(form)
        # Нормализация: в некоторых средах значения формы приходят списками
        normalized: dict[str, object] = {}
        for key, value in raw.items():
            if isinstance(value, list):
                normalized[key] = value[0] if value else ""
            else:
                normalized[key] = value
        return "form", normalized

    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Unsupported Media Type",
    )


async def get_submitted_csrf_token(request: Request) -> object | None:
    for header_name in _CSRF_HEADER_NAMES:
        header_value = request.headers.get(header_name)
        if header_value:
            return header_value

    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type not in _FORM_CONTENT_TYPES:
        return None

    form = await request.form()
    return form.get("csrf_token")


async def require_csrf(request: Request) -> None:
    submitted_token = await get_submitted_csrf_token(request)
    validate_csrf(request, submitted_token)


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if isinstance(token, str) and token:
        return token

    token = secrets.token_urlsafe(32)
    request.session["csrf_token"] = token
    return token
