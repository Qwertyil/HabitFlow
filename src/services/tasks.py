from datetime import UTC, datetime, timedelta
from typing import Any, Literal, overload
from uuid import UUID

from src.exceptions import TaskNotFound
from src.repositories import TaskRepository, ThemeRepository
from src.schemas import (
    TaskCreate,
    TaskCreateAPI,
    TaskInDB,
    TaskResponse,
    TaskStatisticsPage,
    TaskStats,
    TaskUpdate,
    TaskUpdateAPI,
)
from src.validation import validate_user_facing_name

PRIORITY_IDS = {
    "low": UUID("00000000-0000-0000-0000-000000000001"),
    "medium": UUID("00000000-0000-0000-0000-000000000002"),
    "high": UUID("00000000-0000-0000-0000-000000000003"),
}

ID_TO_PRIORITY = {value: key for key, value in PRIORITY_IDS.items()}

# Доступные приоритеты согласно миграции "add_priorities_in_table"
PRIORITIES = {
    "low": {"name": "низкий", "weight": 1, "color": "#22C55E"},
    "medium": {"name": "средний", "weight": 2, "color": "#EAB308"},
    "high": {"name": "высокий", "weight": 3, "color": "#EF4444"},
}
NO_THEME_LABEL = "Без темы"


Status = Literal["active", "completed"]
Sort = Literal["created_at", "updated_at", "name", "priority"]
Order = Literal["asc", "desc"]


class TaskService:
    def __init__(self, task_repo: TaskRepository, theme_repo: ThemeRepository):
        self.task_repo = task_repo
        self.theme_repo = theme_repo

    async def create_task(self, task_data: TaskCreateAPI) -> TaskInDB:
        """Создать новую задачу"""
        validated_name = validate_user_facing_name(
            task_data.name,
            field_label="Название задачи",
        )
        if task_data.theme_id:
            theme = await self.theme_repo.get_by_id(task_data.theme_id)
            if not theme:
                raise ValueError("Theme not found")

        new_task_data = TaskCreate(
            name=validated_name,
            description=task_data.description,
            theme_id=task_data.theme_id,
            priority_id=self.map_priority(task_data.priority),
        )

        return await self.task_repo.add(new_task_data)

    async def get_task(self, task_id: UUID) -> TaskInDB | None:
        """Получить задачу по ID"""
        return await self.task_repo.get_by_id(task_id)

    async def get_task_priorities(self) -> dict[str, dict[str, object]]:
        """Получить приоритеты"""
        return PRIORITIES

    async def get_priority(self, priority_id: UUID) -> str:
        return ID_TO_PRIORITY[priority_id]

    async def delete_task(self, task_id: UUID) -> bool:
        """Удалить задачу"""
        return await self.task_repo.delete(task_id)

    async def update_task(
        self, task_id: UUID, task_data: TaskUpdateAPI
    ) -> TaskInDB | None:
        """Обновить задачу"""
        old_task = await self.get_task(task_id)
        if not old_task:
            raise TaskNotFound

        # Получаем только явно переданные поля
        raw_data = task_data.model_dump(exclude_unset=True)
        if not raw_data:
            return old_task  # ничего не меняем

        update_dict: dict[str, Any] = {}

        if "name" in raw_data:
            update_dict["name"] = validate_user_facing_name(
                raw_data["name"],
                field_label="Название задачи",
            )
        if "description" in raw_data:
            update_dict["description"] = raw_data["description"]

        if "theme_id" in raw_data:
            theme_val = raw_data["theme_id"]
            if theme_val is not None:
                theme = await self.theme_repo.get_by_id(theme_val)
                if not theme:
                    raise ValueError("Theme not found")
            update_dict["theme_id"] = theme_val

        if "priority" in raw_data:
            update_dict["priority_id"] = self.map_priority(raw_data["priority"])

        updated_task = TaskUpdate(**update_dict)
        return await self.task_repo.update(task_id, updated_task)

    async def complete_task(self, task_id: UUID) -> TaskInDB | None:
        """Отметить задачу как выполненную"""
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise TaskNotFound

        update_data = TaskUpdate(completed_at=datetime.now(UTC))
        return await self.task_repo.update(task_id, update_data)

    async def incomplete_task(self, task_id: UUID) -> TaskInDB | None:
        """Отметить задачу как невыполненную"""
        task = await self.task_repo.get_by_id(task_id)
        if not task:
            raise TaskNotFound

        update_data = TaskUpdate(completed_at=None)
        return await self.task_repo.update(task_id, update_data)

    async def list_tasks(
        self,
        page: int = 1,
        per_page: int = 20,
        theme_name: str | None = None,
        status: Status = "active",
        sort: Sort = "created_at",
        order: Order = "desc",
    ) -> tuple[list[TaskResponse], int]:
        skip = (page - 1) * per_page

        theme_id = None
        if theme_name:
            theme = await self.theme_repo.get_by_name(theme_name)
            if not theme:
                return ([], 0)
            theme_id = theme.id

        return await self.task_repo.list_tasks(
            skip=skip,
            limit=per_page,
            theme_id=theme_id,
            status=status,
            sort=sort,
            order=order,
        )

    async def get_task_statistics(
        self, tasks: list[TaskInDB] | None = None
    ) -> TaskStats:
        """Получить статистику по задачам"""
        all_tasks = tasks if tasks is not None else await self.task_repo.list()

        total = len(all_tasks)
        completed = 0
        pending = 0
        by_priority = dict.fromkeys(PRIORITIES, 0)
        by_theme = {}

        for task in all_tasks:
            if task.completed_at:
                completed += 1
            else:
                pending += 1

            if ID_TO_PRIORITY.get(task.priority_id) in by_priority:
                by_priority[ID_TO_PRIORITY[task.priority_id]] += 1

            theme_name = str(task.theme_id) if task.theme_id else "No theme"
            if theme_name not in by_theme:
                by_theme[theme_name] = 0
            by_theme[theme_name] += 1

        return TaskStats(
            total=total,
            completed=completed,
            pending=pending,
            by_priority=by_priority,
            by_theme=by_theme,
        )

    async def get_task_page_statistics(
        self,
        now: datetime | None = None,
        tasks: list[TaskInDB] | None = None,
        theme_names: dict[UUID, str] | None = None,
    ) -> TaskStatisticsPage:
        """Получить расширенную статистику задач для страницы `/stats`."""
        all_tasks = tasks if tasks is not None else await self.task_repo.list()
        theme_names = (
            theme_names if theme_names is not None else await self._get_theme_names()
        )

        reference_time = self._to_utc(now or datetime.now(UTC))
        seven_day_cutoff = reference_time - timedelta(days=7)
        thirty_day_cutoff = reference_time - timedelta(days=30)
        ninety_day_cutoff = reference_time - timedelta(days=90)

        total = len(all_tasks)
        completed = 0
        active = 0
        created_in_7d = 0
        created_in_30d = 0
        created_in_90d = 0
        completed_in_7d = 0
        completed_in_30d = 0
        completed_in_90d = 0
        by_priority = dict.fromkeys(PRIORITIES, 0)
        by_theme: dict[str, int] = {}
        completion_durations_hours: list[float] = []

        for task in all_tasks:
            created_at = self._to_utc(task.created_at)
            completed_at = self._to_utc(task.completed_at)
            is_completed = self._is_completed_by_reference(completed_at, reference_time)
            created_hits = self._get_period_hits(
                created_at,
                reference_time,
                seven_day_cutoff,
                thirty_day_cutoff,
                ninety_day_cutoff,
            )
            completed_hits = self._get_period_hits(
                completed_at,
                reference_time,
                seven_day_cutoff,
                thirty_day_cutoff,
                ninety_day_cutoff,
            )

            if is_completed and completed_at:
                completed += 1
                duration_hours = self._get_completion_duration_hours(
                    created_at, completed_at
                )
                if duration_hours >= 0:
                    completion_durations_hours.append(duration_hours)
            else:
                active += 1

            created_in_7d += created_hits[0]
            created_in_30d += created_hits[1]
            created_in_90d += created_hits[2]
            completed_in_7d += completed_hits[0]
            completed_in_30d += completed_hits[1]
            completed_in_90d += completed_hits[2]

            priority_key = ID_TO_PRIORITY.get(task.priority_id)
            if priority_key in by_priority:
                by_priority[priority_key] += 1

            theme_label = self._get_theme_label(task.theme_id, theme_names)
            by_theme[theme_label] = by_theme.get(theme_label, 0) + 1

        avg_completion_time_hours = None
        if completion_durations_hours:
            avg_completion_time_hours = round(
                sum(completion_durations_hours) / len(completion_durations_hours), 1
            )

        completion_rate = round((completed / total) * 100) if total else 0

        sorted_by_theme = dict(
            sorted(by_theme.items(), key=lambda item: (-item[1], item[0].lower()))
        )

        return TaskStatisticsPage(
            total=total,
            active=active,
            completed=completed,
            completion_rate=completion_rate,
            by_priority=by_priority,
            by_theme=sorted_by_theme,
            created_in_7d=created_in_7d,
            created_in_30d=created_in_30d,
            created_in_90d=created_in_90d,
            completed_in_7d=completed_in_7d,
            completed_in_30d=completed_in_30d,
            completed_in_90d=completed_in_90d,
            avg_completion_time_hours=avg_completion_time_hours,
        )

    async def get_tasks_for_statistics(self) -> list[TaskInDB]:
        """Вернуть owner-scoped snapshot задач для page-level статистики."""
        return await self.task_repo.list()

    def map_priority(self, priority: str | UUID) -> UUID:
        if isinstance(priority, str):
            if priority not in PRIORITY_IDS:
                raise ValueError(f"Invalid priority: {priority}")
            return PRIORITY_IDS[priority]
        if isinstance(priority, UUID):
            if priority not in set(PRIORITY_IDS.values()):
                raise ValueError(f"Invalid priority UUID: {priority}")
            return priority
        raise ValueError("Priority must be str or UUID")

    async def _get_theme_names(self) -> dict[UUID, str]:
        themes = await self.theme_repo.list(limit=None)
        return {theme.id: theme.name for theme in themes}

    @overload
    def _to_utc(self, value: datetime) -> datetime: ...

    @overload
    def _to_utc(self, value: None) -> None: ...

    def _to_utc(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _get_period_hits(
        self,
        value: datetime | None,
        reference_time: datetime,
        seven_day_cutoff: datetime,
        thirty_day_cutoff: datetime,
        ninety_day_cutoff: datetime,
    ) -> tuple[int, int, int]:
        if value is None or value > reference_time:
            return (0, 0, 0)
        return (
            int(value >= seven_day_cutoff),
            int(value >= thirty_day_cutoff),
            int(value >= ninety_day_cutoff),
        )

    def _is_completed_by_reference(
        self, completed_at: datetime | None, reference_time: datetime
    ) -> bool:
        return completed_at is not None and completed_at <= reference_time

    def _get_completion_duration_hours(
        self, created_at: datetime, completed_at: datetime
    ) -> float:
        return (completed_at - created_at).total_seconds() / 3600

    def _get_theme_label(
        self, theme_id: UUID | None, theme_names: dict[UUID, str]
    ) -> str:
        if theme_id is None:
            return NO_THEME_LABEL
        return theme_names.get(theme_id, NO_THEME_LABEL)
