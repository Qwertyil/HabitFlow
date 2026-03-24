import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories import HabitRepository, TaskRepository, ThemeRepository
from src.schemas import TaskUpdate, ThemeCreate
from tests.api_unit.assertions import assert_html_response
from tests.integration.test_habits import create_habit_and_return_id
from tests.integration.test_tasks import create_task_and_return_id

pytestmark = pytest.mark.asyncio


async def test_get_stats_page_smoke(client: AsyncClient) -> None:
    response = await client.get("/stats")

    assert_html_response(response, status_code=200)
    assert 'class="surface-card stats-toolbar"' in response.text
    assert "/stats?range=30d" in response.text
    assert "/stats?range=90d" in response.text
    assert "/stats?range=all" in response.text
    assert 'data-stats-target="overview"' in response.text
    assert 'data-stats-target="themes"' in response.text
    assert 'class="stats-kpi-grid"' in response.text
    assert "Пульс задач" in response.text
    assert "Фокус периода" in response.text
    assert "Создано за неделю" in response.text
    assert "Создано за месяц" not in response.text
    assert "Дневная динамика" in response.text
    assert "Топ тем по числу привычек" in response.text
    assert 'class="stats-insight-list"' in response.text


def _extract_sidebar_stat_value(html: str, element_id: str) -> int:
    pattern = rf'id="{element_id}"[^>]*>\s*(\d+)(?:%|)\s*<'
    match = re.search(pattern, html)
    assert match is not None, f"Sidebar stat element not found: {element_id}"
    return int(match.group(1))


def _extract_sidebar_success_rate_payload(html: str) -> tuple[int, int, int]:
    tag_match = re.search(r'<span[^>]*id="stat-success-rate"[^>]*>', html)
    assert tag_match is not None, "Sidebar success rate element not found"
    tag = tag_match.group(0)

    due_match = re.search(r'data-due-habits-today="(\d+)"', tag)
    completed_match = re.search(r'data-completed-habits-today="(\d+)"', tag)
    value_match = re.search(r">(\d+)%<", html[tag_match.end() - 1 :])

    assert due_match is not None, "Missing sidebar due-habits payload"
    assert completed_match is not None, "Missing sidebar completed-habits payload"
    assert value_match is not None, "Missing sidebar success-rate value"

    return (
        int(due_match.group(1)),
        int(completed_match.group(1)),
        int(value_match.group(1)),
    )


def _assert_task_stat_value(html: str, label: str, value: str) -> None:
    pattern = (
        r'<h2><i class="fas fa-tasks"></i> Задачи</h2>.*?'
        + r"<span>\s*"
        + re.escape(label)
        + r"\s*</span>"
        + r"\s*<strong>\s*"
        + re.escape(value)
        + r"\s*</strong>"
    )
    assert re.search(pattern, html, re.S), f"Expected task stat {label}={value}"


def _assert_habit_stat_value(html: str, label: str, value: str) -> None:
    pattern = (
        r'<h2><i class="fas fa-sync-alt"></i> Привычки</h2>.*?'
        + r"<span>\s*"
        + re.escape(label)
        + r"\s*</span>"
        + r"\s*<strong>\s*"
        + re.escape(value)
        + r"\s*</strong>"
    )
    assert re.search(pattern, html, re.S), f"Expected habit stat {label}={value}"


async def test_stats_page_shows_owner_task_aggregates_only(
    client: AsyncClient,
    session: AsyncSession,
    owner_id: UUID,
    secondary_owner_id: UUID,
) -> None:
    owner_theme = await ThemeRepository(session=session, owner_id=owner_id).add(
        ThemeCreate(name="Статистика Работа", color="#112233")
    )
    foreign_theme = await ThemeRepository(
        session=session, owner_id=secondary_owner_id
    ).add(ThemeCreate(name="Чужая тема", color="#445566"))
    await session.commit()

    await create_task_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-active-task",
    )
    completed_task_id = await create_task_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-completed-task",
        theme_id=owner_theme.id,
    )
    await create_task_and_return_id(
        session,
        owner_id=secondary_owner_id,
        name="foreign-stats-task",
        theme_id=foreign_theme.id,
    )

    await TaskRepository(session=session, owner_id=owner_id).update(
        completed_task_id,
        TaskUpdate(completed_at=datetime.now(UTC)),
    )
    await session.commit()

    response = await client.get("/stats")

    assert_html_response(response, status_code=200)
    _assert_task_stat_value(response.text, "Всего", "2")
    _assert_task_stat_value(response.text, "Активные", "1")
    _assert_task_stat_value(response.text, "Выполненные", "1")
    _assert_task_stat_value(response.text, "Процент выполнения", "50%")
    _assert_task_stat_value(response.text, "Создано за неделю", "2")
    _assert_task_stat_value(response.text, "Завершено за неделю", "1")
    assert "Статистика Работа" in response.text
    assert "Без темы" in response.text
    assert "Чужая тема" not in response.text
    assert "foreign-stats-task" not in response.text


async def test_stats_page_switches_task_period_labels_for_30d(
    client: AsyncClient,
) -> None:
    response = await client.get("/stats?range=30d")

    assert_html_response(response, status_code=200)
    assert "Создано за месяц" in response.text
    assert "Создано за неделю" not in response.text
    assert "Завершено за месяц" in response.text
    assert "Завершено за неделю" not in response.text


async def test_stats_page_supports_90d_and_all_ranges(
    client: AsyncClient,
) -> None:
    response_90d = await client.get("/stats?range=90d")
    assert_html_response(response_90d, status_code=200)
    assert "Создано за квартал" in response_90d.text
    assert "Завершено за квартал" in response_90d.text
    assert "Недельная динамика" in response_90d.text

    response_all = await client.get("/stats?range=all")
    assert_html_response(response_all, status_code=200)
    assert "Создано за всё время" in response_all.text
    assert "Завершено за всё время" in response_all.text
    assert "Месячная динамика" in response_all.text


async def test_stats_page_shows_owner_habit_history_only(
    client: AsyncClient,
    session: AsyncSession,
    owner_id: UUID,
    secondary_owner_id: UUID,
) -> None:
    today = datetime.now(UTC).date()
    weekday = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[today.weekday()]

    owner_theme = await ThemeRepository(session=session, owner_id=owner_id).add(
        ThemeCreate(name="Фокус", color="#223344")
    )
    foreign_theme = await ThemeRepository(
        session=session, owner_id=secondary_owner_id
    ).add(ThemeCreate(name="Чужая привычка", color="#556677"))
    await session.commit()

    owner_daily_habit_id = await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-owner-daily-habit",
        theme_id=owner_theme.id,
        starts_on=today - timedelta(days=6),
    )
    owner_weekly_habit_id = await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-owner-weekly-habit",
        schedule_type="weekly_days",
        schedule_config={"days": [weekday]},
        starts_on=today - timedelta(days=6),
    )
    owner_archived_habit_id = await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-owner-archived-habit",
        theme_id=owner_theme.id,
        starts_on=today - timedelta(days=2),
        ends_on=today - timedelta(days=1),
    )
    foreign_habit_id = await create_habit_and_return_id(
        session,
        owner_id=secondary_owner_id,
        name="stats-foreign-habit",
        theme_id=foreign_theme.id,
        starts_on=today - timedelta(days=6),
    )

    owner_habit_repo = HabitRepository(session=session, owner_id=owner_id)
    await owner_habit_repo.add_completion(
        owner_daily_habit_id, today - timedelta(days=1)
    )
    await owner_habit_repo.add_completion(owner_daily_habit_id, today)
    await owner_habit_repo.add_completion(owner_weekly_habit_id, today)
    await owner_habit_repo.add_completion(
        owner_archived_habit_id, today - timedelta(days=1)
    )

    foreign_habit_repo = HabitRepository(session=session, owner_id=secondary_owner_id)
    await foreign_habit_repo.add_completion(foreign_habit_id, today)
    await session.commit()

    response = await client.get("/stats?range=7d")

    assert_html_response(response, status_code=200)
    _assert_habit_stat_value(response.text, "Всего", "3")
    _assert_habit_stat_value(response.text, "Активные", "2")
    _assert_habit_stat_value(response.text, "Архивные", "1")
    _assert_habit_stat_value(response.text, "На сегодня", "2")
    _assert_habit_stat_value(response.text, "Выполнено сегодня", "2")
    _assert_habit_stat_value(response.text, "Успех сегодня", "100%")
    _assert_habit_stat_value(response.text, "Успех за неделю", "40%")
    _assert_habit_stat_value(response.text, today.strftime("%d.%m"), "2")
    _assert_habit_stat_value(response.text, (today - timedelta(days=1)).strftime("%d.%m"), "2")
    assert "Фокус" in response.text
    assert "Без темы" in response.text
    assert "stats-owner-daily-habit" in response.text
    assert "stats-owner-weekly-habit" in response.text
    assert "Чужая привычка" not in response.text
    assert "stats-foreign-habit" not in response.text


async def test_stats_page_sidebar_matches_home_sidebar_for_shared_metrics(
    client: AsyncClient,
    session: AsyncSession,
    owner_id: UUID,
) -> None:
    today = datetime.now(UTC).date()

    task_id = await create_task_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-shared-completed-task",
    )
    await create_task_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-shared-active-task",
    )
    await TaskRepository(session=session, owner_id=owner_id).update(
        task_id,
        TaskUpdate(completed_at=datetime.now(UTC)),
    )

    await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-shared-due-habit",
        starts_on=today - timedelta(days=2),
    )
    completed_habit_id = await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-shared-completed-habit",
        starts_on=today - timedelta(days=2),
    )
    archived_habit_id = await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="stats-shared-archived-habit",
        starts_on=today - timedelta(days=3),
        ends_on=today - timedelta(days=1),
    )
    habit_repo = HabitRepository(session=session, owner_id=owner_id)
    await habit_repo.add_completion(completed_habit_id, today)
    await habit_repo.add_completion(archived_habit_id, today - timedelta(days=1))
    await session.commit()

    home_response = await client.get("/")
    stats_response = await client.get("/stats")

    assert_html_response(home_response, status_code=200)
    assert_html_response(stats_response, status_code=200)

    shared_stat_ids = [
        "stat-active-tasks",
        "stat-total-habits",
        "stat-active-habits",
        "stat-due-habits-today",
    ]
    for stat_id in shared_stat_ids:
        assert _extract_sidebar_stat_value(
            stats_response.text,
            stat_id,
        ) == _extract_sidebar_stat_value(home_response.text, stat_id)

    assert _extract_sidebar_success_rate_payload(
        stats_response.text
    ) == _extract_sidebar_success_rate_payload(home_response.text)
    _assert_task_stat_value(stats_response.text, "Активные", "1")
    _assert_habit_stat_value(stats_response.text, "Всего", "3")
    _assert_habit_stat_value(stats_response.text, "Активные", "2")
    _assert_habit_stat_value(stats_response.text, "На сегодня", "2")
    _assert_habit_stat_value(stats_response.text, "Выполнено сегодня", "1")
    _assert_habit_stat_value(stats_response.text, "Успех сегодня", "50%")
