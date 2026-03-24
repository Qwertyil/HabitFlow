from datetime import UTC, datetime
from uuid import UUID

from src.schemas import (
    HabitStatisticsPage,
    StatisticsPageData,
    StatsBreakdownItem,
    StatsInsight,
    StatsKpi,
    StatsRange,
    TaskInDB,
    TaskStatisticsPage,
    ThemeStatisticsPage,
)
from src.services.habits import HabitService
from src.services.tasks import NO_THEME_LABEL, TaskService
from src.services.themes import ThemeService

TOP_THEME_LIMIT = 5


class StatisticsService:
    def __init__(
        self,
        task_service: TaskService,
        habit_service: HabitService,
        theme_service: ThemeService,
    ) -> None:
        self.task_service = task_service
        self.habit_service = habit_service
        self.theme_service = theme_service

    async def get_statistics_page_data(
        self, selected_range: StatsRange = "7d"
    ) -> StatisticsPageData:
        reference_time = datetime.now(UTC)
        tasks = await self.task_service.get_tasks_for_statistics()
        theme_names = await self._get_theme_name_map()
        task_stats = await self.task_service.get_task_page_statistics(
            now=reference_time,
            tasks=tasks,
            theme_names=theme_names,
        )
        habit_stats = await self.habit_service.get_habit_page_statistics(
            selected_range,
            reference_time=reference_time,
        )
        theme_stats = self._build_theme_statistics(
            habit_stats=habit_stats,
            reference_time=reference_time,
            tasks=tasks,
            theme_names=theme_names,
        )

        return StatisticsPageData(
            range=selected_range,
            kpis=self._build_kpis(task_stats, habit_stats),
            tasks=task_stats,
            habits=habit_stats,
            themes=theme_stats,
            insights=self._build_insights(habit_stats, theme_stats),
        )

    def _build_kpis(
        self,
        task_stats: TaskStatisticsPage,
        habit_stats: HabitStatisticsPage,
    ) -> list[StatsKpi]:
        return [
            StatsKpi(
                key="active_tasks",
                label="Активные задачи",
                value=task_stats.active,
                hint="Обновляется по реальным задачам пользователя.",
            ),
            StatsKpi(
                key="completed_tasks",
                label="Выполненные задачи",
                value=task_stats.completed,
                hint="Обновляется по реальным задачам пользователя.",
            ),
            StatsKpi(
                key="total_habits",
                label="Всего привычек",
                value=habit_stats.total,
                hint="Считает все привычки пользователя, включая архивные.",
            ),
            StatsKpi(
                key="active_habits",
                label="Активные привычки",
                value=habit_stats.active,
                hint="Показывает только текущие неархивные привычки.",
            ),
            StatsKpi(
                key="due_today",
                label="Привычки на сегодня",
                value=habit_stats.due_today,
                hint="Учитывает только привычки, которые еще актуальны сегодня.",
            ),
            StatsKpi(
                key="completed_today",
                label="Выполнено сегодня",
                value=habit_stats.completed_today,
                hint="Обновляется по истории выполнений привычек.",
            ),
            StatsKpi(
                key="success_rate",
                label="Успех сегодня",
                value=f"{habit_stats.success_rate_today}%",
                hint="Текущий успех по обязательным привычкам на сегодня.",
            ),
        ]

    def _build_theme_statistics(
        self,
        *,
        habit_stats: HabitStatisticsPage,
        reference_time: datetime,
        tasks: list[TaskInDB],
        theme_names: dict[UUID, str],
    ) -> ThemeStatisticsPage:
        task_counts: dict[str, int] = {}
        active_task_counts: dict[str, int] = {}

        for task in tasks:
            theme_label = self._get_task_theme_label(task, theme_names)
            task_counts[theme_label] = task_counts.get(theme_label, 0) + 1
            if self._is_task_active(task, reference_time):
                active_task_counts[theme_label] = (
                    active_task_counts.get(theme_label, 0) + 1
                )

        top_task_themes = self._build_breakdown_items(task_counts)
        busiest_theme = None
        busiest_candidates = self._build_breakdown_items(active_task_counts, limit=1)
        if busiest_candidates:
            busiest_theme = busiest_candidates[0]

        return ThemeStatisticsPage(
            top_task_themes=top_task_themes,
            top_habit_themes=habit_stats.top_themes[:TOP_THEME_LIMIT],
            busiest_theme=busiest_theme,
        )

    def _build_insights(
        self,
        habit_stats: HabitStatisticsPage,
        theme_stats: ThemeStatisticsPage,
    ) -> list[StatsInsight]:
        insights: list[StatsInsight] = []
        remaining_habits = max(habit_stats.due_today - habit_stats.completed_today, 0)

        self._append_insight(
            insights,
            title="Осталось привычек на сегодня",
            description=f"{remaining_habits} из {habit_stats.due_today}",
            severity="warning" if remaining_habits else "success",
        )

        best_streak = self._first_valid_breakdown_item(habit_stats.top_streaks)
        if best_streak is not None:
            self._append_insight(
                insights,
                title="Лучшая серия",
                description=f"{best_streak.label}: {best_streak.value}",
                severity="success",
            )

        if (
            theme_stats.busiest_theme is not None
            and theme_stats.busiest_theme.value > 0
        ):
            self._append_insight(
                insights,
                title="Самая загруженная тема",
                description=(
                    f"{theme_stats.busiest_theme.label}: "
                    f"{theme_stats.busiest_theme.value} активных задач"
                ),
                severity="info",
            )

        return insights

    async def _get_theme_name_map(self) -> dict[UUID, str]:
        themes = await self.theme_service.list_themes(limit=None)
        return {theme.id: theme.name for theme in themes}

    def _get_task_theme_label(
        self,
        task: TaskInDB,
        theme_names: dict[UUID, str],
    ) -> str:
        if task.theme_id is None:
            return NO_THEME_LABEL
        return theme_names.get(task.theme_id, NO_THEME_LABEL)

    def _is_task_active(self, task: TaskInDB, reference_time: datetime) -> bool:
        completed_at = task.completed_at
        if completed_at is None:
            return True
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=UTC)
        else:
            completed_at = completed_at.astimezone(UTC)
        return completed_at > reference_time

    def _build_breakdown_items(
        self, counts: dict[str, int], limit: int = TOP_THEME_LIMIT
    ) -> list[StatsBreakdownItem]:
        return [
            StatsBreakdownItem(label=label, value=value)
            for label, value in sorted(
                counts.items(),
                key=lambda item: (-item[1], item[0].lower()),
            )[:limit]
        ]

    def _append_insight(
        self,
        insights: list[StatsInsight],
        *,
        title: str,
        description: str,
        severity: str,
    ) -> None:
        clean_title = title.strip()
        clean_description = description.strip()
        if not clean_title or not clean_description:
            return
        if any(existing.title == clean_title for existing in insights):
            return
        insights.append(
            StatsInsight(
                title=clean_title,
                description=clean_description,
                severity=severity,
            )
        )

    def _first_valid_breakdown_item(
        self, items: list[StatsBreakdownItem]
    ) -> StatsBreakdownItem | None:
        for item in items:
            if item.label.strip() and item.value > 0:
                return item
        return None
