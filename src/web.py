import os
import re
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.templating import Jinja2Templates

from src.csrf import ensure_csrf_token
from src.schemas import Stats, ThemeResponse
from src.schemas.auth import AuthUser
from src.services.themes import ThemeService

current_dir = os.path.dirname(os.path.abspath(__file__))
templates_dir = os.path.join(current_dir, "templates")
templates = Jinja2Templates(directory=templates_dir)


def get_user_display_name(user: AuthUser | None) -> str | None:
    if user is None:
        return None

    local_part = user.email.split("@", 1)[0].strip()
    if not local_part:
        return user.email

    chunks = [chunk for chunk in re.split(r"[._-]+", local_part) if chunk]
    if not chunks:
        return local_part
    return " ".join(chunk.capitalize() for chunk in chunks[:2])


async def build_template_context(
    request: Request,
    *,
    theme_service: ThemeService,
    statistics: Stats,
    current_user: AuthUser | None = None,
) -> dict[str, Any]:
    themes = await theme_service.list_themes(limit=None)

    params = request.query_params
    if params.get("theme"):
        if params["theme"] == "Все темы":
            request.session["selected_theme"] = None
            selected_theme = None
        else:
            request.session["selected_theme"] = params["theme"]
            selected_theme = params["theme"]
    else:
        selected_theme = request.session.get("selected_theme")

    # Темы заданной в сессии не существует
    if selected_theme is not None and not any(
        theme.name == selected_theme for theme in themes
    ):
        request.session["selected_theme"] = None
        selected_theme = None

    # Добавляем опцию "Все темы"
    no_theme = ThemeResponse(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="Все темы",
        color="#000000",
        is_active=selected_theme is None,
    )
    themes.insert(0, no_theme)

    # Подсвечиваем выбранную тему
    if selected_theme is not None:
        for theme in themes:
            if theme.name == selected_theme:
                theme.is_active = True
                break

    return {
        "request": request,
        "themes": themes,
        "stats": statistics,
        "current_user": current_user,
        "current_user_display_name": get_user_display_name(current_user),
        "csrf_token": ensure_csrf_token(request),
    }


def error_context_updater(context: dict[Any, Any], e: str) -> dict[Any, Any]:
    context.update({"message_type": "error", "title": "Ошибка", "message": str(e)})
    return context
