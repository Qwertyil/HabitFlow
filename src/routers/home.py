from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.dependencies import add_quote_to_context, get_habit_service, get_task_service
from src.services.habits import HabitService
from src.services.tasks import TaskService
from src.utils import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def root(
    request: Request,
    context: dict[str, Any] = Depends(add_quote_to_context),
    task_service: TaskService = Depends(get_task_service),
    habit_service: HabitService = Depends(get_habit_service),
):
    tasks, _ = await task_service.list_tasks(
        per_page=5, theme_name=request.session.get("selected_theme")
    )
    habits, _ = await habit_service.list_habits(
        per_page=4,
        theme_name=request.session.get("selected_theme"),
        due_today_only=True,
    )
    context.update(
        {
            "tasks": tasks,
            "habits": habits,
            "current_page": "home",
            "today_display": date.today().strftime("%d.%m.%Y"),
        }
    )

    return templates.TemplateResponse(request, "index.html", context)
