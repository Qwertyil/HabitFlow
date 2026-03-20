from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import ValidationError
from starlette.datastructures import FormData

from src.csrf import csrf_error_message, require_csrf
from src.dependencies import (
    get_habit_service,
    get_template_context,
    get_user_habit_service,
)
from src.exceptions import HabitNotFound
from src.schemas import (
    HabitCompletionResult,
    HabitScheduleFilter,
    HabitUpdateAPI,
    Response,
)
from src.schemas.habits import HabitCreateAPI
from src.services.habits import HabitService
from src.utils import error_context_updater, templates

router = APIRouter(prefix="/habits", tags=["Habits"])
_WRITE_ROUTE_DEPENDENCIES = [Depends(require_csrf)]


@router.get(
    "/",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Returns habits page",
)
async def habits_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Literal["todays", "completed", "active", "archived"] = "todays",
    schedule_type: HabitScheduleFilter = "all",
    sort: Literal["created_at", "updated_at", "name", "streak"] = Query("created_at"),
    order: Literal["asc", "desc"] = Query("desc"),
    context: dict[str, Any] = Depends(get_template_context),
    habits_service: HabitService = Depends(get_habit_service),
):
    habits, habits_count = await habits_service.list_habits(
        page=page,
        per_page=per_page,
        schedule_type=schedule_type,
        theme_name=request.session.get("selected_theme"),
        status=status,
        sort=sort,
        order=order,
        due_today_only=status == "todays",
    )
    total_pages = (habits_count + per_page - 1) // per_page if habits_count else 0
    context.update(
        {
            "habits": habits,
            "habits_count": habits_count,
            "habits_page": page,
            "habits_per_page": per_page,
            "habits_total_pages": total_pages,
            "habits_has_prev": page > 1,
            "habits_has_next": total_pages > 0 and page < total_pages,
            "current_page": "habits",
            "hide_sidebar": True,
        }
    )
    return templates.TemplateResponse(request, "habits/habits_list.html", context)


@router.get(
    "/new",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Returns habit creation page",
)
async def create_habit_page(
    request: Request,
    context: dict[str, Any] = Depends(get_template_context),
):
    context.update({"current_page": "habits", "hide_sidebar": True})
    return templates.TemplateResponse(request, "habits/habits_form.html", context)


@router.get(
    "/{id}",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Returns habit edition page",
)
async def habit_page(
    request: Request,
    id: UUID,
    context: dict[str, Any] = Depends(get_template_context),
    habits_service: HabitService = Depends(get_habit_service),
):
    habit = await habits_service.get_habit(id)
    if not habit:
        context = error_context_updater(context, "Привычка не найдена")
        return templates.TemplateResponse(
            request, "message.html", context, status_code=status.HTTP_404_NOT_FOUND
        )
    context.update({"habit": habit, "current_page": "habits", "hide_sidebar": True})
    return templates.TemplateResponse(request, "habits/habits_form.html", context)


@router.post(
    "/",
    response_class=RedirectResponse,
    status_code=status.HTTP_303_SEE_OTHER,
    summary="Creates new habit and redirects to habits list",
)
async def create_habit(
    request: Request,
    context: dict[str, Any] = Depends(get_template_context),
    habits_service: HabitService = Depends(get_user_habit_service),
):
    expects_json = "application/json" in request.headers.get("content-type", "").lower()
    try:
        await require_csrf(request)
    except HTTPException as exc:
        if expects_json:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
            )
        context.update(
            {
                "current_page": "habits",
                "hide_sidebar": True,
                "error_message": csrf_error_message(),
            }
        )
        return templates.TemplateResponse(
            request,
            "habits/habits_form.html",
            context,
            status_code=exc.status_code,
        )

    try:
        if expects_json:
            payload = await request.json()
        else:
            form = await request.form()
            schedule_type = str(form.get("schedule_type", ""))
            payload = {
                "name": form.get("name"),
                "description": form.get("description") or None,
                "theme_id": form.get("theme_id"),
                "schedule_type": schedule_type,
                "schedule_config": _build_schedule_config_from_form(
                    form, schedule_type
                ),
                "starts_on": form.get("starts_on") or None,
                "ends_on": form.get("ends_on") or None,
            }

        habit_data = HabitCreateAPI.model_validate(payload)
        await habits_service.create_habit(habit_data)
    except (ValidationError, ValueError) as exc:
        if expects_json:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": {"code": "bad_request", "message": str(exc)},
                },
            )
        context = error_context_updater(context, f"Ошибка создания привычки: {exc}")
        context.update({"current_page": "habits", "hide_sidebar": True})
        return templates.TemplateResponse(
            request,
            "habits/habits_form.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if expects_json:
        return JSONResponse(status_code=status.HTTP_201_CREATED, content={"ok": True})
    return RedirectResponse(url="/habits", status_code=status.HTTP_303_SEE_OTHER)


def _build_schedule_config_from_form(
    form: FormData, schedule_type: str
) -> dict[str, object]:
    if schedule_type == "daily":
        return {}
    if schedule_type == "weekly_days":
        return {"days": form.getlist("weekly_days")}
    if schedule_type == "monthly_day":
        return {
            "day": _as_positive_int_or_raise(form.get("monthly_day"), "День месяца")
        }
    if schedule_type == "yearly_date":
        return {
            "month": _as_positive_int_or_raise(form.get("yearly_month"), "Месяц"),
            "day": _as_positive_int_or_raise(form.get("yearly_day"), "День"),
        }
    if schedule_type == "interval_cycle":
        return {
            "active_days": _as_positive_int_or_raise(
                form.get("interval_active_days"), "Дней подряд (N)"
            ),
            "break_days": _as_positive_int_or_raise(
                form.get("interval_break_days"), "Дней перерыва (K)"
            ),
        }
    return {}


def _as_positive_int_or_raise(value: object, label: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'"{label}" должно быть целым числом больше 0') from exc
    if parsed < 1:
        raise ValueError(f'"{label}" должно быть целым числом больше 0')
    return parsed


@router.put(
    "/{id}",
    response_model=Response,
    summary="Updates habit",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Bad request - validation error"},
        404: {"description": "Habit not found"},
    },
)
async def update_habit(
    id: UUID,
    habit_data: HabitUpdateAPI,
    habits_service: HabitService = Depends(get_user_habit_service),
):
    try:
        res = await habits_service.update_habit(id, habit_data)
        if not res:
            return JSONResponse(
                status_code=500,
                content={
                    "error": {"code": "internal_error", "message": "Habit not updated"}
                },
            )
        return Response(message="success")
    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "bad_request", "message": str(e)}},
        )
    except HabitNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "Habit not found"}},
        )
    except RuntimeError:
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "Internal server error"}
            },
        )


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deletes habit",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        204: {"description": "Habit deleted"},
        404: {"description": "Habit not found"},
        500: {"description": "Internal server error"},
    },
)
async def delete_habit(
    id: UUID,
    habits_service: HabitService = Depends(get_user_habit_service),
):
    try:
        res = await habits_service.delete_habit(id)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from None
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Habit not found",
        )


@router.patch(
    "/{id}/complete",
    response_model=HabitCompletionResult,
    summary="Marks habit as completed",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        404: {"description": "Habit not found"},
        500: {"description": "Internal server error"},
    },
)
async def complete_habit(
    id: UUID,
    habits_service: HabitService = Depends(get_user_habit_service),
):
    try:
        habit_completion_result = await habits_service.complete_habit(id)
    except HabitNotFound:
        raise HTTPException(status_code=404, detail="Habit not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Internal server error") from None
    return habit_completion_result


@router.patch(
    "/{id}/incomplete",
    response_model=HabitCompletionResult,
    summary="Marks habit as incomplete",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        404: {"description": "Habit not found"},
        500: {"description": "Internal server error"},
    },
)
async def incomplete_habit(
    id: UUID,
    habits_service: HabitService = Depends(get_user_habit_service),
):
    try:
        habit_completion_result = await habits_service.incomplete_habit(id)
    except HabitNotFound:
        raise HTTPException(status_code=404, detail="Habit not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Internal server error") from None
    return habit_completion_result
