from uuid import UUID

from sqlalchemy import and_, desc, distinct, func, select

from src.database.models import Habit, Task, Theme
from src.schemas import ThemeCreate, ThemeInDB, ThemeUpdate

from .owned_base import OwnedRepository


class ThemeRepository(
    OwnedRepository[ThemeCreate, ThemeInDB, ThemeUpdate, Theme, UUID]
):
    """
    Репозиторий для работы с темами
    Наследуется от GenericSqlRepository без кэширования
    """

    _model = Theme
    _create_schema = ThemeCreate
    _read_schema = ThemeInDB
    _update_schema = ThemeUpdate

    async def get_by_name(self, name: str) -> ThemeInDB | None:
        """Получить тему по имени"""
        stmt = self._construct_list_stmt(name=name)
        result = await self._session.execute(stmt)
        theme = result.scalars().first()
        return self._convert_model_to_read(theme) if theme else None

    async def get_by_color(self, color: str) -> ThemeInDB | None:
        """Получить тему по цвету"""
        stmt = self._construct_list_stmt(color=color)
        result = await self._session.execute(stmt)
        theme = result.scalars().first()
        return self._convert_model_to_read(theme) if theme else None

    async def get_existing_colors_list(
        self, skip: int = 0, limit: int = 100
    ) -> set[str]:
        """Получить список существующих цветов"""
        themes = await self.list(skip=skip, limit=limit)
        return {theme.color for theme in themes}

    async def list_by_ids(self, theme_ids: list[UUID]) -> dict[UUID, ThemeInDB]:
        if not theme_ids:
            return {}

        themes = await self.list(
            limit=None,
            extra_conditions=[Theme.id.in_(set(theme_ids))],
        )
        return {theme.id: theme for theme in themes}

    async def list_with_counts(
        self, skip: int = 0, limit: int = 100
    ) -> list[tuple[ThemeInDB, int, int]]:
        query = (
            select(
                Theme,
                func.count(distinct(Task.id)).label("task_count"),
                func.count(distinct(Habit.id)).label("habit_count"),
            )
            .select_from(Theme)
            .outerjoin(
                Task,
                and_(Theme.id == Task.theme_id, self._owner_filter(Task.owner_id)),
            )
            .outerjoin(
                Habit,
                and_(Theme.id == Habit.theme_id, self._owner_filter(Habit.owner_id)),
            )
            .where(self._owner_filter(Theme.owner_id))
            .group_by(Theme.id)
            .order_by(desc(Theme.created_at), desc(Theme.id))
            .offset(skip)
            .limit(limit)
        )

        result = await self._session.execute(query)
        rows = result.all()
        # возвращаем список кортежей (Theme, task_count, habit_count)
        return [(row[0], row[1], row[2]) for row in rows]

    async def count_themes(self) -> int:
        total = await self._session.scalar(
            select(func.count(Theme.id)).where(self._owner_filter(Theme.owner_id))
        )
        return int(total or 0)
