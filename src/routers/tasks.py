from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.csrf import csrf_error_message, require_csrf
from src.dependencies import (
    get_task_service,
    get_template_context,
    get_user_task_service,
)
from src.exceptions import TaskNotFound
from src.schemas import Response
from src.schemas.tasks import (
    TaskCreateAPI,
    TaskMarkCompleted,
    TaskUpdateAPI,
)
from src.services import TaskService
from src.utils import error_context_updater, templates

router = APIRouter(prefix="/tasks", tags=["Tasks"])
_WRITE_ROUTE_DEPENDENCIES = [Depends(require_csrf)]


@router.get(
    "/",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Returns tasks page",
)
async def tasks_page(
    request: Request,
    context: dict[str, Any] = Depends(get_template_context),
    task_service: TaskService = Depends(get_task_service),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    status: Literal["active", "completed"] = "active",
    sort: Literal["created_at", "updated_at", "name", "priority"] = Query("created_at"),
    order: Literal["asc", "desc"] = Query("desc"),
):
    tasks, tasks_count = await task_service.list_tasks(
        page=page,
        per_page=per_page,
        theme_name=request.session.get("selected_theme"),
        status=status,
        sort=sort,
        order=order,
    )
    context.update(
        {"tasks": tasks, "tasks_count": tasks_count, "current_page": "tasks"}
    )
    return templates.TemplateResponse(request, "tasks/tasks_list.html", context)


@router.get(
    "/new",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Returns task creation page",
)
async def create_task_page(
    request: Request,
    context: dict[str, Any] = Depends(get_template_context),
    service: TaskService = Depends(get_task_service),
):
    context.update(
        {
            "current_page": "tasks",
            "hide_sidebar": True,
            "priorities": await service.get_task_priorities(),
            "task": {},  # Empty task object for the form
        }
    )
    return templates.TemplateResponse(request, "tasks/tasks_form.html", context)


@router.get(
    "/{id}",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Returns task edition page",
)
async def task_page(
    request: Request,
    id: UUID,
    context: dict[str, Any] = Depends(get_template_context),
    service: TaskService = Depends(get_task_service),
):
    task = await service.get_task(id)
    if not task:
        context = error_context_updater(context, "Задача не найдена")
        return templates.TemplateResponse(
            request,
            "message.html",
            context,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    priority = await service.get_priority(task.priority_id)  # Getting priority NAME
    context.update(
        {
            "current_page": "tasks",
            "hide_sidebar": True,
            "priorities": await service.get_task_priorities(),
            "task": {
                "id": id,
                "name": task.name,
                "description": task.description,
                "theme_id": task.theme_id,
                "priority": priority,
            },
        }
    )
    return templates.TemplateResponse(request, "tasks/tasks_form.html", context)


@router.post(
    "/",
    response_class=RedirectResponse,
    status_code=status.HTTP_303_SEE_OTHER,
    summary="Creates new task and redirects to tasks list",
    responses={
        303: {"description": "Redirect to tasks list"},
        400: {"description": "Bad request - validation error"},
        500: {"description": "Internal server error"},
    },
)
async def create_task(
    request: Request,
    task_data: Annotated[TaskCreateAPI, Form()],
    context: dict[str, Any] = Depends(get_template_context),
    service: TaskService = Depends(get_user_task_service),
):
    try:
        await require_csrf(request)
    except HTTPException as exc:
        context = error_context_updater(context, csrf_error_message())
        return templates.TemplateResponse(
            request,
            "message.html",
            context,
            status_code=exc.status_code,
        )

    try:
        res = await service.create_task(task_data)
        if not res:
            context = error_context_updater(context, "Задача не создана")
            return templates.TemplateResponse(
                request,
                "message.html",
                context,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return RedirectResponse(url="/tasks", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as e:
        context = error_context_updater(context, str(e))
        return templates.TemplateResponse(
            request, "message.html", context, status_code=status.HTTP_400_BAD_REQUEST
        )
    except RuntimeError as e:
        context = error_context_updater(context, str(e))
        return templates.TemplateResponse(
            request,
            "message.html",
            context,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deletes Task",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
)
async def delete_task(
    task_id: UUID,
    service: TaskService = Depends(get_user_task_service),
):
    try:
        res = await service.delete_task(task_id)
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        ) from None
    if not res:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )


@router.patch(
    "/{id}/complete",
    summary="Marks task as completed",
    response_model=TaskMarkCompleted,
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        404: {"description": "Task not found"},
        500: {"description": "Internal server error"},
    },
)
async def complete_task(
    id: UUID,
    service: TaskService = Depends(get_user_task_service),
):
    try:
        res = await service.complete_task(id)
        return TaskMarkCompleted(success=True, completed=True, task=res)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="Task not found") from None
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.patch(
    "/{id}/incomplete",
    summary="Marks task as incompleted",
    response_model=TaskMarkCompleted,
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        404: {"description": "Task not found"},
        500: {"description": "Internal server error"},
    },
)
async def incomplete_task(
    id: UUID,
    service: TaskService = Depends(get_user_task_service),
):
    try:
        res = await service.incomplete_task(id)
        return TaskMarkCompleted(success=True, completed=False, task=res)
    except TaskNotFound:
        raise HTTPException(status_code=404, detail="Task not found") from None
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.put(
    "/{id}",
    response_model=Response,
    summary="Updates task",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        500: {"description": "Internal server error"},
        400: {"description": "Bad request - validation error"},
        404: {"description": "Task not found"},
    },
)
async def update_task(
    id: UUID,
    task_data: TaskUpdateAPI,
    service: TaskService = Depends(get_user_task_service),
):
    try:
        res = await service.update_task(id, task_data)
        if not res:
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "internal_error",
                        "message": "Задача не обновлена",
                    }
                },
            )
        return Response(message="success")

    except ValueError as e:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "bad_request", "message": str(e)}},
        )
    except TaskNotFound:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "Задача не найдена"}},
        )
    except RuntimeError:
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "Internal server error"}
            },
        )
