from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse

from src.dependencies import (
    get_current_user,
    get_statistics_service,
    get_theme_service,
)
from src.schemas import Stats
from src.schemas.auth import AuthUser
from src.schemas.statistics import StatisticsPageData, StatsRange
from src.services.statistics import StatisticsService
from src.services.themes import ThemeService
from src.web import build_template_context, templates

router = APIRouter(tags=["Statistics"])


async def get_stats_page_data(
    statistics_service: StatisticsService = Depends(get_statistics_service),
    selected_range: Annotated[StatsRange, Query(alias="range")] = "7d",
) -> StatisticsPageData:
    return await statistics_service.get_statistics_page_data(selected_range)


async def get_stats_page_context(
    request: Request,
    page_data: StatisticsPageData = Depends(get_stats_page_data),
    theme_service: ThemeService = Depends(get_theme_service),
    current_user: Annotated[AuthUser | None, Depends(get_current_user)] = None,
) -> dict[str, Any]:
    return await build_template_context(
        request,
        theme_service=theme_service,
        statistics=get_stats_from_page_data(page_data),
        current_user=current_user,
    )


def get_stats_from_page_data(page_data: StatisticsPageData) -> Stats:
    return Stats(
        total_tasks=page_data.tasks.total,
        active_tasks=page_data.tasks.active,
        total_habits=page_data.habits.total,
        success_rate=page_data.habits.success_rate_today,
        active_habits=page_data.habits.active,
        due_habits_today=page_data.habits.due_today,
        completed_habits_today=page_data.habits.completed_today,
    )


@router.get(
    "/stats",
    response_class=HTMLResponse,
    status_code=status.HTTP_200_OK,
    summary="Returns statistics page",
)
async def stats_page(
    request: Request,
    context: dict[str, Any] = Depends(get_stats_page_context),
    page_data: StatisticsPageData = Depends(get_stats_page_data),
):
    context.update(
        {
            "current_page": "stats",
            "hide_sidebar": True,
            "page_data": page_data,
        }
    )
    return templates.TemplateResponse(request, "stats/stats_page.html", context)
