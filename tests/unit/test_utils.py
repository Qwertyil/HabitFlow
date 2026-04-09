from __future__ import annotations

from uuid import uuid4

import pytest
from starlette.requests import Request

from src.schemas import Stats, ThemeResponse
from src.schemas.statistics import (
    HabitStatisticsPage,
    StatisticsPageData,
    TaskStatisticsPage,
)
from src.dependencies import get_stats, get_template_context
from src.routers.stats import get_stats_from_page_data


class _DummyTaskStats:
    total = 10
    pending = 4


class _DummyHabitStats:
    total = 7
    active = 5
    due_today = 3
    completed_today = 3
    success_rate = 100


class _DummyTaskService:
    async def get_task_statistics(self) -> _DummyTaskStats:
        return _DummyTaskStats()


class _DummyHabitService:
    async def get_habit_statistics(self) -> _DummyHabitStats:
        return _DummyHabitStats()


class _DummyThemeService:
    def __init__(self, themes: list[ThemeResponse]) -> None:
        self._themes = themes

    async def list_themes(self, skip: int = 0, limit: int | None = 100) -> list[ThemeResponse]:
        return list(self._themes)


def _request(path: str = "/", query: str = "", session: dict[str, object] | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": query.encode(),
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "session": session if session is not None else {},
    }
    return Request(scope)


def _theme(name: str, is_active: bool = False) -> ThemeResponse:
    return ThemeResponse(id=uuid4(), name=name, color="#112233", is_active=is_active)


@pytest.mark.asyncio
async def test_get_stats_maps_task_and_habit_stats() -> None:
    stats = await get_stats(
        task_service=_DummyTaskService(),
        habits_service=_DummyHabitService(),
    )

    assert stats == Stats(
        total_tasks=10,
        active_tasks=4,
        total_habits=7,
        success_rate=100,
        active_habits=5,
        due_habits_today=3,
        completed_habits_today=3,
    )


def test_get_stats_from_page_data_maps_sidebar_fields() -> None:
    stats = get_stats_from_page_data(
        StatisticsPageData(
            range="7d",
            tasks=TaskStatisticsPage(total=10, active=4),
            habits=HabitStatisticsPage(
                total=7,
                active=5,
                due_today=3,
                completed_today=2,
                success_rate_today=67,
            ),
        )
    )

    assert stats == Stats(
        total_tasks=10,
        active_tasks=4,
        total_habits=7,
        success_rate=67,
        active_habits=5,
        due_habits_today=3,
        completed_habits_today=2,
    )


@pytest.mark.asyncio
async def test_get_template_context_selects_theme_from_query_and_marks_active() -> None:
    request = _request(path="/tasks/", query="theme=Work", session={})
    service = _DummyThemeService([_theme("Work"), _theme("Home")])

    context = await get_template_context(
        request=request,
        theme_service=service,
        statistics=Stats(total_tasks=0, active_tasks=0, total_habits=0, success_rate=0),
    )

    assert request.session["selected_theme"] == "Work"
    active_names = [t.name for t in context["themes"] if t.is_active]
    assert active_names == ["Work"]


@pytest.mark.asyncio
async def test_get_template_context_resets_selection_for_all_themes_query() -> None:
    request = _request(path="/tasks/", query="theme=%D0%92%D1%81%D0%B5+%D1%82%D0%B5%D0%BC%D1%8B", session={"selected_theme": "Work"})
    service = _DummyThemeService([_theme("Work"), _theme("Home")])

    context = await get_template_context(
        request=request,
        theme_service=service,
        statistics=Stats(total_tasks=1, active_tasks=1, total_habits=1, success_rate=100),
    )

    assert request.session["selected_theme"] is None
    assert context["themes"][0].name == "Все темы"
    assert context["themes"][0].is_active is True


@pytest.mark.asyncio
async def test_get_template_context_clears_stale_theme_from_session() -> None:
    request = _request(path="/habits/", session={"selected_theme": "Ghost"})
    service = _DummyThemeService([_theme("Work"), _theme("Home")])

    context = await get_template_context(
        request=request,
        theme_service=service,
        statistics=Stats(total_tasks=0, active_tasks=0, total_habits=0, success_rate=0),
    )

    assert request.session["selected_theme"] is None
    assert context["themes"][0].name == "Все темы"
    assert context["themes"][0].is_active is True
