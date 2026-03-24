from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from src.exceptions import HabitNotFound
from src.schemas.habits import (
    HabitCreateAPI,
    HabitInDB,
    HabitResponse,
    HabitScheduleType,
    HabitUpdateAPI,
)
from src.services.habits import HabitService


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 0, 0, 0, tzinfo=UTC)


def _mk_habit(
    *,
    habit_id: UUID | None = None,
    name: str = "habit",
    schedule_type: HabitScheduleType = "daily",
    schedule_config: dict[str, object] | None = None,
    theme_id: UUID | None = None,
    starts_on: date | None = None,
    ends_on: date | None = None,
    is_archived: bool = False,
    created_at: datetime | None = None,
) -> HabitInDB:
    now = created_at or _dt(2026, 1, 1)
    return HabitInDB(
        id=habit_id or uuid4(),
        name=name,
        description=None,
        theme_id=theme_id,
        schedule_type=schedule_type,
        schedule_config=schedule_config or {},
        starts_on=starts_on,
        ends_on=ends_on,
        is_archived=is_archived,
        created_at=now,
        updated_at=now,
    )


class DummyHabitRepo:
    def __init__(self) -> None:
        self.get_by_id_result: HabitInDB | None = None
        self.add_result: HabitInDB | None = None
        self.list_habits_result: tuple[list[HabitInDB], int] = ([], 0)
        self.list_result: list[HabitInDB] = []
        self.list_habits_last_kwargs: dict[str, object] | None = None
        self.completions: dict[UUID, set[date]] = {}
        self.archive_expired_calls = 0
        self.archive_expired_dates: list[date] = []
        self.list_completion_dates_calls = 0
        self.list_completion_dates_by_habit_calls = 0

    async def add(self, data: HabitCreateAPI) -> HabitInDB:
        if self.add_result is not None:
            return self.add_result
        self.add_result = _mk_habit(
            schedule_type=data.schedule_type,
            schedule_config=data.schedule_config,
            theme_id=data.theme_id,
            starts_on=data.starts_on,
            ends_on=data.ends_on,
        )
        return self.add_result

    async def get_by_id(self, habit_id: UUID) -> HabitInDB | None:
        if self.get_by_id_result is not None and self.get_by_id_result.id == habit_id:
            return self.get_by_id_result
        if self.add_result is not None and self.add_result.id == habit_id:
            return self.add_result
        return self.get_by_id_result

    async def update(self, habit_id: UUID, data: HabitUpdateAPI) -> HabitInDB | None:
        updates = data.model_dump(exclude_unset=True)
        if self.get_by_id_result is not None and self.get_by_id_result.id == habit_id:
            self.get_by_id_result = self.get_by_id_result.model_copy(update=updates)
            return self.get_by_id_result
        if self.add_result is not None and self.add_result.id == habit_id:
            self.add_result = self.add_result.model_copy(update=updates)
            return self.add_result
        if self.get_by_id_result is not None:
            self.get_by_id_result = self.get_by_id_result.model_copy(update=updates)
            return self.get_by_id_result
        return None

    async def delete(self, habit_id: UUID) -> bool:
        return True

    async def list_habits(self, **kwargs: object) -> tuple[list[HabitInDB], int]:
        self.list_habits_last_kwargs = kwargs
        return self.list_habits_result

    async def list(self, **kwargs: object) -> list[HabitInDB]:
        return list(self.list_result)

    async def list_completion_dates(self, habit_id: UUID) -> set[date]:
        self.list_completion_dates_calls += 1
        return set(self.completions.get(habit_id, set()))

    async def list_completion_dates_by_habit(
        self, habit_ids: list[UUID] | None = None
    ) -> dict[UUID, set[date]]:
        self.list_completion_dates_by_habit_calls += 1
        ids = list(self.completions) if habit_ids is None else habit_ids
        return {habit_id: set(self.completions.get(habit_id, set())) for habit_id in ids}

    async def add_completion(self, habit_id: UUID, completed_on: date) -> bool:
        current = self.completions.setdefault(habit_id, set())
        before = len(current)
        current.add(completed_on)
        return len(current) > before

    async def remove_completion(self, habit_id: UUID, completed_on: date) -> bool:
        current = self.completions.setdefault(habit_id, set())
        if completed_on in current:
            current.remove(completed_on)
            return True
        return False

    async def archive_expired_habits(self, today: date) -> int:
        self.archive_expired_calls += 1
        self.archive_expired_dates.append(today)
        archived_count = 0

        if (
            self.get_by_id_result is not None
            and self.get_by_id_result.ends_on is not None
            and self.get_by_id_result.ends_on < today
            and not self.get_by_id_result.is_archived
        ):
            self.get_by_id_result = self.get_by_id_result.model_copy(
                update={"is_archived": True}
            )
            archived_count += 1

        if (
            self.add_result is not None
            and self.add_result.ends_on is not None
            and self.add_result.ends_on < today
            and not self.add_result.is_archived
        ):
            self.add_result = self.add_result.model_copy(update={"is_archived": True})
            archived_count += 1

        updated_list_result: list[HabitInDB] = []
        for habit in self.list_result:
            if (
                habit.ends_on is not None
                and habit.ends_on < today
                and not habit.is_archived
            ):
                updated_list_result.append(
                    habit.model_copy(update={"is_archived": True})
                )
                archived_count += 1
            else:
                updated_list_result.append(habit)
        self.list_result = updated_list_result

        return archived_count


class _ThemeObj:
    def __init__(
        self, theme_id: UUID, name: str = "Theme", color: str = "#112233"
    ) -> None:
        self.id = theme_id
        self.name = name
        self.color = color


class DummyThemeRepo:
    def __init__(self) -> None:
        self.by_id = None
        self.by_id_map: dict[UUID, object] = {}
        self.by_name = None
        self.get_by_id_calls = 0

    async def get_by_id(self, theme_id: UUID) -> object | None:
        self.get_by_id_calls += 1
        if theme_id in self.by_id_map:
            return self.by_id_map[theme_id]
        return self.by_id

    async def get_by_name(self, theme_name: str) -> object | None:
        return self.by_name


@pytest.mark.asyncio
async def test_create_habit_validates_theme_exists_when_theme_id_set() -> None:
    habit_repo = DummyHabitRepo()
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    with pytest.raises(ValueError, match="Theme not found"):
        await service.create_habit(
            HabitCreateAPI(
                name="h",
                theme_id=uuid4(),
                schedule_type="daily",
                schedule_config={},
            )
        )


@pytest.mark.asyncio
async def test_create_habit_rejects_markup_like_name() -> None:
    habit_repo = DummyHabitRepo()
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    with pytest.raises(ValueError, match="символы < или >"):
        await service.create_habit(
            HabitCreateAPI(
                name="<script>habit</script>",
                schedule_type="daily",
                schedule_config={},
            )
        )


@pytest.mark.asyncio
async def test_update_habit_raises_when_habit_missing() -> None:
    habit_repo = DummyHabitRepo()
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    with pytest.raises(HabitNotFound):
        await service.update_habit(uuid4(), HabitUpdateAPI(name="new"))


@pytest.mark.asyncio
async def test_update_habit_rejects_control_characters_in_name() -> None:
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(habit_id=habit_id)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    with pytest.raises(ValueError, match="управляющие символы"):
        await service.update_habit(habit_id, HabitUpdateAPI(name="bad\u0007habit"))


@pytest.mark.asyncio
async def test_update_habit_uses_existing_schedule_when_only_config_is_updated() -> (
    None
):
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(
        habit_id=habit_id,
        schedule_type="interval_cycle",
        schedule_config={"active_days": 1, "break_days": 2},
    )
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    res = await service.update_habit(
        habit_id,
        HabitUpdateAPI(schedule_config={"active_days": 2, "break_days": 2}),
    )

    assert res is not None
    assert res.schedule_type == "interval_cycle"
    assert res.schedule_config == {"active_days": 2, "break_days": 2}


@pytest.mark.asyncio
async def test_list_habits_returns_empty_when_theme_not_found() -> None:
    habit_repo = DummyHabitRepo()
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    items, total = await service.list_habits(theme_name="Missing")
    assert items == []
    assert total == 0
    assert habit_repo.list_habits_last_kwargs is None


@pytest.mark.asyncio
async def test_list_habits_passes_filters_to_repo() -> None:
    theme_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = (
        [
            HabitResponse(
                **_mk_habit(theme_id=theme_id).model_dump(),
                current_streak=0,
            )
        ],
        1,
    )

    theme_repo = DummyThemeRepo()
    theme_repo.by_name = _ThemeObj(theme_id)
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    items, total = await service.list_habits(
        page=2,
        per_page=5,
        theme_name="Work",
        status="archived",
        schedule_type="weekly_days",
        sort="name",
        order="asc",
    )

    assert total == 1
    assert len(items) == 1
    assert habit_repo.list_habits_last_kwargs is not None
    actual_kwargs = dict(habit_repo.list_habits_last_kwargs)
    assert isinstance(actual_kwargs.pop("today", None), date)
    assert actual_kwargs == {
        "skip": 5,
        "limit": 5,
        "theme_id": theme_id,
        "status": "archived",
        "schedule_type": "weekly_days",
        "sort": "name",
        "order": "asc",
    }


@pytest.mark.asyncio
async def test_list_habits_populates_theme_name_and_color() -> None:
    theme_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = (
        [HabitResponse(**_mk_habit(theme_id=theme_id).model_dump(), current_streak=0)],
        1,
    )

    theme_repo = DummyThemeRepo()
    theme_repo.by_id = _ThemeObj(theme_id, name="Work", color="#A1B2C3")
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    items, total = await service.list_habits()

    assert total == 1
    assert len(items) == 1
    assert items[0].theme_name == "Work"
    assert items[0].theme_color == "#A1B2C3"
    assert theme_repo.get_by_id_calls == 1


@pytest.mark.asyncio
async def test_complete_habit_rejects_future_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(habit_id=habit_id)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    today = date(2026, 1, 10)
    monkeypatch.setattr(service, "_today_utc", lambda: today)
    tomorrow = today + timedelta(days=1)
    with pytest.raises(ValueError, match="future date"):
        await service.complete_habit(habit_id, tomorrow)


@pytest.mark.asyncio
async def test_complete_habit_is_idempotent_for_same_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(habit_id=habit_id)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    today = date(2026, 1, 10)
    monkeypatch.setattr(service, "_today_utc", lambda: today)
    first = await service.complete_habit(habit_id, today)
    second = await service.complete_habit(habit_id, today)

    assert first.changed is True
    assert second.changed is False
    assert second.completed is True


@pytest.mark.asyncio
async def test_incomplete_habit_returns_changed_false_when_date_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(habit_id=habit_id)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    today = date(2026, 1, 10)
    monkeypatch.setattr(service, "_today_utc", lambda: today)
    res = await service.incomplete_habit(habit_id, today)

    assert res.changed is False
    assert res.completed is False


@pytest.mark.asyncio
async def test_create_habit_archives_when_interval_has_ended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit_repo = DummyHabitRepo()
    expired_end = date(2026, 1, 1)
    habit_repo.add_result = _mk_habit(ends_on=expired_end, is_archived=False)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: date(2026, 1, 2))

    res = await service.create_habit(
        HabitCreateAPI(
            name="expired",
            schedule_type="daily",
            schedule_config={},
            ends_on=expired_end,
        )
    )

    assert res.is_archived is True


@pytest.mark.asyncio
async def test_complete_habit_rejects_archived_habit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(habit_id=habit_id, is_archived=True)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    today = date(2026, 1, 10)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    with pytest.raises(ValueError, match="archived habit"):
        await service.complete_habit(habit_id, today)


@pytest.mark.asyncio
async def test_list_habits_marks_completed_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit = _mk_habit()
    today = date(2026, 1, 2)
    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = ([habit], 1)
    habit_repo.completions[habit.id] = {today}
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    items, total = await service.list_habits(status="active")

    assert total == 1
    assert len(items) == 1
    assert items[0].completed_today is True


@pytest.mark.asyncio
async def test_list_habits_marks_due_today_false_for_not_scheduled_habit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 10)  # Saturday
    not_due_weekly = _mk_habit(
        schedule_type="weekly_days",
        schedule_config={"days": ["mon"]},
    )
    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = ([not_due_weekly], 1)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    items, total = await service.list_habits(status="active")

    assert total == 1
    assert len(items) == 1
    assert items[0].due_today is False


@pytest.mark.asyncio
async def test_list_habits_due_today_only_respects_start_and_end_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 15)
    due_habit = _mk_habit(
        habit_id=uuid4(),
        starts_on=today - timedelta(days=1),
        ends_on=today + timedelta(days=3),
    )
    starts_in_future = _mk_habit(
        habit_id=uuid4(),
        starts_on=today + timedelta(days=1),
    )
    already_ended = _mk_habit(
        habit_id=uuid4(),
        ends_on=today - timedelta(days=1),
    )

    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = ([due_habit, starts_in_future, already_ended], 3)
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    items, total = await service.list_habits(status="active", due_today_only=True)

    assert total == 1
    assert len(items) == 1
    assert items[0].id == due_habit.id


@pytest.mark.asyncio
async def test_list_habits_due_today_only_filters_weekly_monthly_yearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 2, 28)  # Saturday
    weekly_due = _mk_habit(
        habit_id=uuid4(),
        schedule_type="weekly_days",
        schedule_config={"days": ["sat"]},
    )
    weekly_not_due = _mk_habit(
        habit_id=uuid4(),
        schedule_type="weekly_days",
        schedule_config={"days": ["mon"]},
    )
    monthly_due = _mk_habit(
        habit_id=uuid4(),
        schedule_type="monthly_day",
        schedule_config={"day": 31},
    )
    monthly_not_due = _mk_habit(
        habit_id=uuid4(),
        schedule_type="monthly_day",
        schedule_config={"day": 27},
    )
    yearly_due = _mk_habit(
        habit_id=uuid4(),
        schedule_type="yearly_date",
        schedule_config={"month": 2, "day": 29},
    )
    yearly_not_due = _mk_habit(
        habit_id=uuid4(),
        schedule_type="yearly_date",
        schedule_config={"month": 3, "day": 1},
    )

    all_habits = [
        weekly_due,
        weekly_not_due,
        monthly_due,
        monthly_not_due,
        yearly_due,
        yearly_not_due,
    ]

    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = (all_habits, len(all_habits))
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    items, total = await service.list_habits(status="active", due_today_only=True)

    due_ids = {weekly_due.id, monthly_due.id, yearly_due.id}
    assert total == 3
    assert {item.id for item in items} == due_ids


@pytest.mark.asyncio
async def test_list_habits_due_today_only_uses_completion_history_for_interval_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 5)
    due_after_break = _mk_habit(
        habit_id=uuid4(),
        schedule_type="interval_cycle",
        schedule_config={"active_days": 2, "break_days": 2},
        starts_on=date(2026, 1, 1),
    )
    not_due_during_break = _mk_habit(
        habit_id=uuid4(),
        schedule_type="interval_cycle",
        schedule_config={"active_days": 2, "break_days": 2},
        starts_on=date(2026, 1, 1),
    )
    due_after_partial_block = _mk_habit(
        habit_id=uuid4(),
        schedule_type="interval_cycle",
        schedule_config={"active_days": 2, "break_days": 2},
        starts_on=date(2026, 1, 1),
    )
    completed_today = _mk_habit(
        habit_id=uuid4(),
        schedule_type="interval_cycle",
        schedule_config={"active_days": 2, "break_days": 2},
        starts_on=date(2026, 1, 1),
    )

    all_habits = [
        due_after_break,
        not_due_during_break,
        due_after_partial_block,
        completed_today,
    ]

    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = (all_habits, len(all_habits))
    habit_repo.completions[due_after_break.id] = {date(2026, 1, 1), date(2026, 1, 2)}
    habit_repo.completions[not_due_during_break.id] = {
        date(2026, 1, 3),
        date(2026, 1, 4),
    }
    habit_repo.completions[due_after_partial_block.id] = {date(2026, 1, 4)}
    habit_repo.completions[completed_today.id] = {
        date(2026, 1, 1),
        date(2026, 1, 2),
        today,
    }

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    items, total = await service.list_habits(status="active", due_today_only=True)

    assert total == 2
    assert {item.id for item in items} == {
        due_after_break.id,
        due_after_partial_block.id,
    }


@pytest.mark.asyncio
async def test_list_habits_calculates_progress_for_interval_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit = _mk_habit(
        schedule_type="interval_cycle",
        schedule_config={"active_days": 2, "break_days": 2},
        starts_on=date(2026, 1, 1),
        ends_on=date(2026, 1, 8),
    )
    today = date(2026, 1, 8)
    habit_repo = DummyHabitRepo()
    habit_repo.list_habits_result = ([habit], 1)
    habit_repo.completions[habit.id] = {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 5),
    }
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    items, total = await service.list_habits(status="active")

    assert total == 1
    assert len(items) == 1
    assert items[0].progress_percent == 75.0


@pytest.mark.asyncio
async def test_complete_habit_returns_interval_cycle_streak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(
        habit_id=habit_id,
        schedule_type="interval_cycle",
        schedule_config={"active_days": 2, "break_days": 1},
        starts_on=date(2026, 1, 1),
    )
    habit_repo.completions[habit_id] = {
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 4),
    }
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: date(2026, 1, 5))

    result = await service.complete_habit(habit_id, date(2026, 1, 5))

    assert result.new_streak == 4


@pytest.mark.asyncio
async def test_complete_habit_rejects_non_scheduled_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    habit_id = uuid4()
    habit_repo = DummyHabitRepo()
    habit_repo.get_by_id_result = _mk_habit(
        habit_id=habit_id,
        schedule_type="weekly_days",
        schedule_config={"days": ["mon"]},
    )
    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: date(2026, 1, 10))  # Saturday

    with pytest.raises(ValueError, match="non-scheduled date"):
        await service.complete_habit(habit_id, date(2026, 1, 10))


@pytest.mark.asyncio
async def test_get_habit_statistics_returns_total_and_success_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 5)
    active_completed = _mk_habit(habit_id=uuid4(), is_archived=False)
    active_not_completed = _mk_habit(habit_id=uuid4(), is_archived=False)
    archived = _mk_habit(habit_id=uuid4(), is_archived=True)

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [active_completed, active_not_completed, archived]
    habit_repo.completions[active_completed.id] = {today}

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_statistics()

    assert stats.total == 3
    assert stats.active == 2
    assert stats.due_today == 2
    assert stats.completed_today == 1
    assert stats.success_rate == 50
    assert habit_repo.list_completion_dates_by_habit_calls == 1
    assert habit_repo.list_completion_dates_calls == 0


@pytest.mark.asyncio
async def test_get_habit_statistics_uses_due_today_denominator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 5)  # Monday
    due_and_completed = _mk_habit(
        habit_id=uuid4(),
        schedule_type="weekly_days",
        schedule_config={"days": ["mon"]},
        is_archived=False,
    )
    active_not_due_today = _mk_habit(
        habit_id=uuid4(),
        schedule_type="weekly_days",
        schedule_config={"days": ["tue"]},
        is_archived=False,
    )

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [due_and_completed, active_not_due_today]
    habit_repo.completions[due_and_completed.id] = {today}

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_statistics()

    assert stats.total == 2
    assert stats.active == 2
    assert stats.due_today == 1
    assert stats.completed_today == 1
    assert stats.success_rate == 100


@pytest.mark.asyncio
async def test_get_habit_page_statistics_counts_period_success_by_due_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 7)
    habit = _mk_habit(habit_id=uuid4(), name="Daily focus", is_archived=False)

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [habit]
    habit_repo.completions[habit.id] = {
        date(2026, 1, 1),
        date(2026, 1, 3),
        date(2026, 1, 7),
    }

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_page_statistics("7d")

    assert stats.success_rate_today == 100
    assert stats.success_rate_7d == 43
    assert stats.success_rate_30d == 43
    assert stats.success_rate_90d == 43
    assert stats.success_rate_all == 43
    assert habit_repo.list_completion_dates_by_habit_calls == 1
    assert habit_repo.list_completion_dates_calls == 0


@pytest.mark.asyncio
async def test_get_habit_page_statistics_keeps_habits_archived_today_in_historical_widgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 7)
    expired_habit = _mk_habit(
        habit_id=uuid4(),
        name="Ended habit",
        starts_on=date(2026, 1, 5),
        ends_on=date(2026, 1, 6),
        is_archived=False,
    )

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [expired_habit]
    habit_repo.completions[expired_habit.id] = {date(2026, 1, 6)}

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_page_statistics("7d")

    assert stats.active == 0
    assert stats.archived == 1
    assert stats.due_today == 0
    assert stats.completed_today == 0
    assert stats.success_rate_today == 0
    assert stats.success_rate_7d == 50
    assert stats.success_rate_30d == 50
    assert stats.success_rate_90d == 50
    assert stats.success_rate_all == 50
    assert [item.value for item in stats.completions_by_day] == [0, 0, 0, 0, 0, 1, 0]


@pytest.mark.asyncio
async def test_get_habit_page_statistics_counts_interval_cycle_due_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 5)
    habit = _mk_habit(
        habit_id=uuid4(),
        name="Cycle habit",
        schedule_type="interval_cycle",
        schedule_config={"active_days": 2, "break_days": 2},
        starts_on=date(2026, 1, 1),
    )

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [habit]
    habit_repo.completions[habit.id] = {date(2026, 1, 1), date(2026, 1, 2)}

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_page_statistics("7d")

    assert stats.due_today == 1
    assert stats.completed_today == 0
    assert stats.success_rate_today == 0
    assert stats.success_rate_7d == 67
    assert stats.success_rate_30d == 67
    assert stats.success_rate_90d == 67
    assert stats.success_rate_all == 67
    assert [item.value for item in stats.completions_by_day] == [0, 0, 1, 1, 0, 0, 0]


@pytest.mark.asyncio
async def test_get_habit_page_statistics_supports_all_time_monthly_trend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 3, 14)
    old_habit = _mk_habit(
        habit_id=uuid4(),
        name="Archive-proof habit",
        starts_on=date(2026, 1, 10),
    )

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [old_habit]
    habit_repo.completions[old_habit.id] = {
        date(2026, 1, 10),
        date(2026, 2, 5),
        date(2026, 2, 12),
        date(2026, 3, 1),
    }

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_page_statistics("all")

    assert [item.label for item in stats.completions_by_day] == ["01.26", "02.26", "03.26"]
    assert [item.value for item in stats.completions_by_day] == [1, 2, 1]


@pytest.mark.asyncio
async def test_get_habit_page_statistics_excludes_archived_habits_from_active_widgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 7)
    active_theme_id = uuid4()
    archived_theme_id = uuid4()
    active_habit = _mk_habit(
        habit_id=uuid4(),
        name="Active habit",
        theme_id=active_theme_id,
        is_archived=False,
    )
    archived_habit = _mk_habit(
        habit_id=uuid4(),
        name="Archived habit",
        theme_id=archived_theme_id,
        is_archived=True,
    )

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [active_habit, archived_habit]
    habit_repo.completions[active_habit.id] = {today}
    habit_repo.completions[archived_habit.id] = {today - timedelta(days=1), today}

    theme_repo = DummyThemeRepo()
    theme_repo.by_id_map = {
        active_theme_id: _ThemeObj(active_theme_id, name="Work"),
        archived_theme_id: _ThemeObj(archived_theme_id, name="Archive"),
    }
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_page_statistics("7d")

    assert stats.total == 2
    assert stats.active == 1
    assert stats.archived == 1
    assert stats.due_today == 1
    assert stats.completed_today == 1
    assert stats.schedule_type_distribution == {"Ежедневно": 1}
    assert [(item.label, item.value) for item in stats.top_streaks] == [
        ("Active habit", 1)
    ]
    assert [(item.label, item.value) for item in stats.top_themes] == [("Work", 1)]


@pytest.mark.asyncio
async def test_get_habit_page_statistics_sorts_top_streaks_stably(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 5)
    top_habit = _mk_habit(habit_id=uuid4(), name="Workout")
    alpha_habit = _mk_habit(habit_id=uuid4(), name="Alpha")
    beta_habit = _mk_habit(habit_id=uuid4(), name="Beta")

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [beta_habit, alpha_habit, top_habit]
    habit_repo.completions[top_habit.id] = {
        date(2026, 1, 3),
        date(2026, 1, 4),
        date(2026, 1, 5),
    }
    habit_repo.completions[alpha_habit.id] = {date(2026, 1, 4), date(2026, 1, 5)}
    habit_repo.completions[beta_habit.id] = {date(2026, 1, 4), date(2026, 1, 5)}

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_page_statistics("7d")

    assert [item.label for item in stats.top_streaks] == ["Workout", "Alpha", "Beta"]
    assert [item.value for item in stats.top_streaks] == [3, 2, 2]


@pytest.mark.asyncio
async def test_get_habit_page_statistics_fills_zero_value_days_in_trend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    today = date(2026, 1, 7)
    habit = _mk_habit(habit_id=uuid4(), name="Walk")

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [habit]
    habit_repo.completions[habit.id] = {date(2026, 1, 2), date(2026, 1, 4)}

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: today)

    stats = await service.get_habit_page_statistics("7d")

    assert [item.label for item in stats.completions_by_day] == [
        "01.01",
        "02.01",
        "03.01",
        "04.01",
        "05.01",
        "06.01",
        "07.01",
    ]
    assert [item.value for item in stats.completions_by_day] == [0, 1, 0, 1, 0, 0, 0]


@pytest.mark.asyncio
async def test_get_habit_page_statistics_uses_explicit_reference_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference_time = datetime(2026, 3, 14, 23, 59, 59, tzinfo=UTC)
    habit = _mk_habit(habit_id=uuid4(), name="Night habit")

    habit_repo = DummyHabitRepo()
    habit_repo.list_result = [habit]
    habit_repo.completions[habit.id] = {date(2026, 3, 14)}

    theme_repo = DummyThemeRepo()
    service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)
    monkeypatch.setattr(service, "_today_utc", lambda: date(2026, 3, 15))

    stats = await service.get_habit_page_statistics(
        "7d",
        reference_time=reference_time,
    )

    assert habit_repo.archive_expired_dates == [date(2026, 3, 14)]
    assert stats.due_today == 1
    assert stats.completed_today == 1
    assert [item.label for item in stats.completions_by_day] == [
        "08.03",
        "09.03",
        "10.03",
        "11.03",
        "12.03",
        "13.03",
        "14.03",
    ]
    assert [item.value for item in stats.top_streaks] == [1]
