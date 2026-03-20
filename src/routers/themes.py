from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from src.csrf import csrf_error_message, require_csrf
from src.dependencies import (
    get_template_context,
    get_theme_service,
    get_user_theme_service,
)
from src.schemas import ThemeCreate, ThemeUpdate
from src.services import ThemeService
from src.services.themes import THEME_COLORS
from src.utils import templates

router = APIRouter(prefix="/themes", tags=["Themes"])
_WRITE_ROUTE_DEPENDENCIES = [Depends(require_csrf)]


@router.get(
    "/",
    status_code=status.HTTP_200_OK,
    response_class=HTMLResponse,
    summary="Returns all themes list page",
)
async def get_themes(
    request: Request,
    context: dict[str, Any] = Depends(get_template_context),
    themes_service: ThemeService = Depends(get_theme_service),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    themes_list, themes_count = await themes_service.list_themes_with_counts(
        page=page, per_page=per_page
    )
    total_pages = (themes_count + per_page - 1) // per_page if themes_count else 0
    if themes_count == 0 and page != 1:
        return RedirectResponse(
            url=f"{request.url.path}?per_page={per_page}",
            status_code=status.HTTP_302_FOUND,
        )
    if total_pages > 0 and page > total_pages:
        return RedirectResponse(
            url=f"{request.url.path}?page={total_pages}&per_page={per_page}",
            status_code=status.HTTP_302_FOUND,
        )

    context.update(
        {
            "current_page": "themes",
            "hide_sidebar": True,
            "themes_list": themes_list,
            "themes_count": themes_count,
            "themes_page": page,
            "themes_per_page": per_page,
            "themes_total_pages": total_pages,
            "themes_has_prev": page > 1,
            "themes_has_next": total_pages > 0 and page < total_pages,
        }
    )
    return templates.TemplateResponse(request, "themes/themes_list.html", context)


@router.get(
    "/new",
    status_code=status.HTTP_200_OK,
    response_class=HTMLResponse,
    summary="Returns new theme creation page",
)
async def create_theme_page(
    request: Request,
    context: dict[str, Any] = Depends(get_template_context),
    service: ThemeService = Depends(get_theme_service),
):
    existing_colors = await service.get_existing_colors()
    context.update(
        {
            "current_page": "themes",
            "hide_sidebar": True,
            "colors": THEME_COLORS - existing_colors,
        }
    )
    return templates.TemplateResponse(request, "themes/themes_form.html", context)


@router.post(
    "/",
    status_code=status.HTTP_303_SEE_OTHER,
    response_class=RedirectResponse,
    summary="Creates new theme and redirects to themes list page",
)
async def create_theme(
    request: Request,
    theme_data: Annotated[ThemeCreate, Form()],
    context: dict[str, Any] = Depends(get_template_context),
    service: ThemeService = Depends(get_user_theme_service),
):
    try:
        await require_csrf(request)
    except HTTPException as exc:
        context.update(
            {
                "message_type": "error",
                "title": "Ошибка",
                "message": csrf_error_message(),
            }
        )
        return templates.TemplateResponse(
            request,
            "message.html",
            context,
            status_code=exc.status_code,
        )

    try:
        res = await service.create_theme(theme_data)
        if not res:
            context.update(
                {
                    "message_type": "error",
                    "title": "Ошибка",
                    "message": "Тема не создана",
                }
            )
            return templates.TemplateResponse(
                request,
                "message.html",
                context,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return RedirectResponse(url="/themes", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as e:
        context.update(
            {
                "request": request,
                "message_type": "error",
                "title": "Ошибка",
                "message": str(e),
            }
        )
        return templates.TemplateResponse(
            request, "message.html", context, status_code=status.HTTP_400_BAD_REQUEST
        )
    except RuntimeError as e:
        context.update({"message_type": "error", "title": "Ошибка", "message": str(e)})
        return templates.TemplateResponse(
            request,
            "message.html",
            context,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_class=HTMLResponse,
    summary="Gets theme by id for update",
    responses={
        404: {"description": "Theme not found"},
    },
)
async def get_theme(
    id: UUID,
    request: Request,
    context: dict[str, Any] = Depends(get_template_context),
    service: ThemeService = Depends(get_theme_service),
):
    theme = await service.get_theme_by_id(id)
    if not theme:
        context.update(
            {
                "message_type": "error",
                "title": "Ошибка",
                "message": "Тема не найдена",
            }
        )
        return templates.TemplateResponse(
            request,
            "message.html",
            context,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    existing_colors = await service.get_existing_colors()
    colors = list(THEME_COLORS - existing_colors)
    colors.insert(0, theme.color)
    context.update(
        {
            "current_page": "themes",
            "hide_sidebar": True,
            "theme_id": str(theme.id),
            "theme_name": theme.name,
            "colors": colors,
        }
    )
    return templates.TemplateResponse(request, "themes/themes_update.html", context)


@router.put(
    "/{id}",
    status_code=status.HTTP_200_OK,
    response_class=JSONResponse,
    summary="Updates theme",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
    responses={
        400: {"description": "Bad request"},
        404: {"description": "Theme not found"},
    },
)
async def update_theme(
    id: UUID,
    theme_data: ThemeUpdate,
    service: ThemeService = Depends(get_user_theme_service),
):
    theme = await service.get_theme_by_id(id)
    if not theme:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Theme with id {id} not found",
        )
    try:
        res = await service.update_theme(theme, theme_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from None
    if not res:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
    return {
        "status": "success",
        "theme": {"id": res.id, "name": res.name, "color": res.color},
    }


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    description="Deletes theme",
    dependencies=_WRITE_ROUTE_DEPENDENCIES,
)
async def delete_theme(
    id: UUID,
    service: ThemeService = Depends(get_user_theme_service),
):
    try:
        res = await service.delete_theme(id)
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
