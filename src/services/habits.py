from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from src.exceptions import HabitNotFound
from src.repositories import HabitRepository, ThemeRepository
from src.schemas.habits import (
    WEEKDAY_ORDER,
    HabitCompletionResult,
    HabitCreate,
    HabitCreateAPI,
    HabitInDB,
    HabitOrder,
    HabitResponse,
    HabitScheduleFilter,
    HabitSort,
    HabitStatistics,
    HabitStatus,
    HabitUpdate,
    HabitUpdateAPI,
    Weekday,
    normalize_schedule_config,
)
from src.schemas.statistics import HabitStatisticsPage, StatsBreakdownItem, StatsRange
from src.schemas.themes import ThemeInDB
from src.validation import validate_user_facing_name

NO_THEME_LABEL = "Без темы"
SCHEDULE_TYPE_LABELS = {
    "daily": "Ежедневно",
    "weekly_days": "Дни недели",
    "monthly_day": "День месяца",
    "yearly_date": "Дата года",
    "interval_cycle": "Интервально",
}
TOP_LIST_LIMIT = 5


@dataclass(slots=True)
class _TrendBuckets:
    start: date
    daily_counts: dict[date, int] | None = None
    weekly_counts: dict[tuple[date, date], int] | None = None
    monthly_counts: dict[tuple[int, int], int] | None = None


@dataclass(slots=True)
class _PageStatisticsTotals:
    due_today: int
    completed_today: int
    schedule_type_counts: dict[str, int]
    top_theme_counts: dict[str, int]
    streak_candidates: list[tuple[int, str, datetime, UUID]]


class HabitService:
    def __init__(self, habit_repo: HabitRepository, theme_repo: ThemeRepository):
        self.habit_repo = habit_repo
        self.theme_repo = theme_repo

    async def create_habit(self, habit_data: HabitCreateAPI) -> HabitInDB:
        validated_name = validate_user_facing_name(
            habit_data.name,
            field_label="Название привычки",
        )
        if habit_data.theme_id:
            theme = await self.theme_repo.get_by_id(habit_data.theme_id)
            if not theme:
                raise ValueError("Theme not found")

        normalized_config = normalize_schedule_config(
            habit_data.schedule_type,
            habit_data.schedule_config,
        )
        create_data = HabitCreate(
            name=validated_name,
            description=habit_data.description,
            theme_id=habit_data.theme_id,
            schedule_type=habit_data.schedule_type,
            schedule_config=normalized_config,
            starts_on=habit_data.starts_on,
            ends_on=habit_data.ends_on,
        )
        created = await self.habit_repo.add(create_data)

        if self._should_be_archived_by_interval(created, self._today_utc()):
            archived = await self.habit_repo.update(
                created.id, HabitUpdate(is_archived=True)
            )
            if archived is not None:
                return archived

        return created

    async def get_habit(self, habit_id: UUID) -> HabitInDB | None:
        await self.habit_repo.archive_expired_habits(self._today_utc())
        return await self.habit_repo.get_by_id(habit_id)

    async def delete_habit(self, habit_id: UUID) -> bool:
        return await self.habit_repo.delete(habit_id)

    async def update_habit(
        self, habit_id: UUID, habit_data: HabitUpdateAPI
    ) -> HabitInDB | None:
        old_habit = await self.get_habit(habit_id)
        if not old_habit:
            raise HabitNotFound

        raw_data = habit_data.model_dump(exclude_unset=True)
        if not raw_data:
            return old_habit

        raw_data = await self._prepare_habit_update_data(raw_data, old_habit)

        update_data = HabitUpdate(**raw_data)
        return await self.habit_repo.update(habit_id, update_data)

    async def _prepare_habit_update_data(
        self, raw_data: dict[str, Any], old_habit: HabitInDB
    ) -> dict[str, Any]:
        self._normalize_updated_name(raw_data)
        await self._validate_updated_theme(raw_data)
        self._normalize_updated_schedule(raw_data, old_habit)
        self._normalize_updated_dates(raw_data, old_habit)
        return raw_data

    def _normalize_updated_name(self, raw_data: dict[str, Any]) -> None:
        if "name" not in raw_data:
            return

        raw_data["name"] = validate_user_facing_name(
            raw_data["name"],
            field_label="Название привычки",
        )

    async def _validate_updated_theme(self, raw_data: dict[str, Any]) -> None:
        if "theme_id" not in raw_data or raw_data["theme_id"] is None:
            return

        theme = await self.theme_repo.get_by_id(raw_data["theme_id"])
        if not theme:
            raise ValueError("Theme not found")

    def _normalize_updated_schedule(
        self, raw_data: dict[str, Any], old_habit: HabitInDB
    ) -> None:
        if "schedule_type" not in raw_data and "schedule_config" not in raw_data:
            return

        schedule_type = raw_data.get("schedule_type", old_habit.schedule_type)
        schedule_config = raw_data.get("schedule_config", old_habit.schedule_config)
        raw_data["schedule_type"] = schedule_type
        raw_data["schedule_config"] = normalize_schedule_config(
            schedule_type, schedule_config
        )

    def _normalize_updated_dates(
        self, raw_data: dict[str, Any], old_habit: HabitInDB
    ) -> None:
        if "starts_on" not in raw_data and "ends_on" not in raw_data:
            return

        starts_on = raw_data.get("starts_on", old_habit.starts_on)
        ends_on = raw_data.get("ends_on", old_habit.ends_on)
        if starts_on and ends_on and ends_on < starts_on:
            raise ValueError("ends_on must be greater than or equal to starts_on")

        raw_data["starts_on"] = starts_on
        raw_data["ends_on"] = ends_on
        if (
            ends_on is not None
            and ends_on < self._today_utc()
            and not raw_data.get("is_archived")
        ):
            raw_data["is_archived"] = True

    async def list_habits(
        self,
        *,
        page: int = 1,
        per_page: int = 20,
        theme_name: str | None = None,
        status: HabitStatus = "todays",
        schedule_type: HabitScheduleFilter = "all",
        sort: HabitSort = "created_at",
        order: HabitOrder = "desc",
        due_today_only: bool = False,
    ) -> tuple[list[HabitResponse], int]:
        today = self._today_utc()
        await self.habit_repo.archive_expired_habits(today)

        skip = (page - 1) * per_page

        theme_id = None
        if theme_name:
            theme = await self.theme_repo.get_by_name(theme_name)
            if not theme:
                return ([], 0)
            theme_id = theme.id

        if due_today_only:
            habits = await self._list_habits_for_due_today_filter(
                per_page=per_page,
                theme_id=theme_id,
                today=today,
                status=status,
                schedule_type=schedule_type,
                sort=sort,
                order=order,
            )
        else:
            habits, total = await self.habit_repo.list_habits(
                skip=skip,
                limit=per_page,
                theme_id=theme_id,
                today=today,
                status=status,
                schedule_type=schedule_type,
                sort=sort,
                order=order,
            )

        completion_dates_by_habit = await self._get_completion_dates_by_habit(habits)
        themes_by_id = await self._get_themes_by_habit(habits)

        items: list[HabitResponse] = []
        for habit in habits:
            item = await self._build_habit_response(
                habit,
                today=today,
                completion_dates=completion_dates_by_habit[habit.id],
                theme=(
                    themes_by_id.get(habit.theme_id)
                    if habit.theme_id is not None
                    else None
                ),
            )
            if due_today_only and not item.due_today:
                continue
            items.append(item)

        if sort == "streak":
            reverse = order == "desc"
            items = sorted(
                items,
                key=lambda item: (item.current_streak, item.created_at),
                reverse=reverse,
            )

        if due_today_only:
            total = len(items)
            items = items[skip : skip + per_page]

        return items, total

    async def _list_habits_for_due_today_filter(
        self,
        *,
        per_page: int,
        theme_id: UUID | None,
        today: date,
        status: HabitStatus,
        schedule_type: HabitScheduleFilter,
        sort: HabitSort,
        order: HabitOrder,
    ) -> list[HabitInDB]:
        batch_size = max(per_page, 100)
        skip = 0
        total = 0
        habits: list[HabitInDB] = []

        while True:
            batch, total = await self.habit_repo.list_habits(
                skip=skip,
                limit=batch_size,
                theme_id=theme_id,
                today=today,
                status=status,
                schedule_type=schedule_type,
                sort=sort,
                order=order,
            )
            if not batch:
                break
            habits.extend(batch)
            skip += len(batch)
            if skip >= total:
                break

        return habits

    async def _build_habit_response(
        self,
        habit: HabitInDB,
        *,
        today: date,
        completion_dates: set[date],
        theme: ThemeInDB | None = None,
    ) -> HabitResponse:
        completed_today = today in completion_dates
        item = HabitResponse(
            id=habit.id,
            name=habit.name,
            description=habit.description,
            theme_id=habit.theme_id,
            theme_name=theme.name if theme else None,
            theme_color=theme.color if theme else None,
            schedule_type=habit.schedule_type,
            schedule_config=habit.schedule_config,
            starts_on=habit.starts_on,
            ends_on=habit.ends_on,
            is_archived=habit.is_archived,
            created_at=habit.created_at,
            updated_at=habit.updated_at,
            current_streak=await self._calculate_streak(
                habit, completion_dates=completion_dates
            ),
            completed_today=completed_today,
            due_today=self._is_habit_due_today(
                habit,
                today=today,
                completion_dates=completion_dates,
                completed_today=completed_today,
            ),
            progress_percent=self._calculate_progress_percent(
                habit, completion_dates, today
            ),
        )
        return item

    def _is_habit_due_today(
        self,
        habit: HabitInDB,
        *,
        today: date,
        completion_dates: set[date],
        completed_today: bool,
        respect_archive: bool = True,
    ) -> bool:
        if (respect_archive and habit.is_archived) or completed_today:
            return False

        starts_on = habit.starts_on or habit.created_at.date()
        if today < starts_on:
            return False
        if habit.ends_on is not None and today > habit.ends_on:
            return False

        if habit.schedule_type == "daily":
            return True

        if habit.schedule_type == "weekly_days":
            days = self._weekday_indexes(habit.schedule_config["days"])
            return today.weekday() in days

        if habit.schedule_type == "monthly_day":
            target_day = self._get_int_config(habit.schedule_config, "day")
            return (
                self._monthly_expected_date(today.year, today.month, target_day)
                == today
            )

        if habit.schedule_type == "yearly_date":
            target_month = self._get_int_config(habit.schedule_config, "month")
            target_day = self._get_int_config(habit.schedule_config, "day")
            return (
                self._yearly_expected_date(today.year, target_month, target_day)
                == today
            )

        return self._is_interval_cycle_due_today(
            habit, today=today, completion_dates=completion_dates
        )

    def _is_interval_cycle_due_today(
        self,
        habit: HabitInDB,
        *,
        today: date,
        completion_dates: set[date],
    ) -> bool:
        anchor_date = self._schedule_anchor_date(habit)
        if today < anchor_date:
            return False

        active_days = self._get_int_config(habit.schedule_config, "active_days")
        break_days = self._get_int_config(habit.schedule_config, "break_days")

        past_completions = sorted(
            completed_on
            for completed_on in completion_dates
            if anchor_date <= completed_on < today
        )
        if not past_completions:
            return True

        last_completed = past_completions[-1]
        completion_set = set(past_completions)

        current_active_run = 1
        cursor = last_completed
        while current_active_run < active_days:
            prev = cursor - timedelta(days=1)
            if prev not in completion_set:
                break
            current_active_run += 1
            cursor = prev

        if current_active_run >= active_days:
            next_due_date = last_completed + timedelta(days=break_days + 1)
        else:
            next_due_date = last_completed + timedelta(days=1)

        return today >= next_due_date

    async def get_habit_statistics(self) -> HabitStatistics:
        today = self._today_utc()
        await self.habit_repo.archive_expired_habits(today)
        habits = await self.habit_repo.list()

        total = len(habits)
        active_habits = [habit for habit in habits if not habit.is_archived]
        active = len(active_habits)
        completion_dates_by_habit = await self._get_completion_dates_by_habit(
            active_habits
        )

        due_today = 0
        completed_today = 0
        for habit in active_habits:
            completion_dates = completion_dates_by_habit[habit.id]
            is_completed_today = today in completion_dates
            if is_completed_today:
                completed_today += 1
            if is_completed_today or self._is_habit_due_today(
                habit,
                today=today,
                completion_dates=completion_dates,
                completed_today=is_completed_today,
            ):
                due_today += 1

        success_rate = round((completed_today / due_today) * 100) if due_today else 0
        return HabitStatistics(
            total=total,
            active=active,
            due_today=due_today,
            completed_today=completed_today,
            success_rate=success_rate,
        )

    async def get_habit_page_statistics(
        self,
        selected_range: StatsRange = "7d",
        *,
        reference_time: datetime | None = None,
    ) -> HabitStatisticsPage:
        today = self._resolve_reference_date(reference_time)
        await self.habit_repo.archive_expired_habits(today)
        habits = await self.habit_repo.list()
        active_habits = [habit for habit in habits if not habit.is_archived]

        completion_dates_by_habit = await self._get_completion_dates_by_habit(habits)
        themes_by_id = await self._get_themes_by_habit(active_habits)
        all_time_start = self._all_time_period_start(
            habits, completion_dates_by_habit, today
        )
        trend_buckets = self._initialize_trend_buckets(
            selected_range, all_time_start, today
        )
        self._populate_trend_buckets(
            completion_dates_by_habit=completion_dates_by_habit,
            trend_buckets=trend_buckets,
            today=today,
        )
        totals = await self._collect_page_statistics_totals(
            active_habits=active_habits,
            completion_dates_by_habit=completion_dates_by_habit,
            today=today,
            themes_by_id=themes_by_id,
        )
        completions_by_period = self._build_completion_breakdown(trend_buckets)

        return HabitStatisticsPage(
            total=len(habits),
            active=len(active_habits),
            archived=len(habits) - len(active_habits),
            due_today=totals.due_today,
            completed_today=totals.completed_today,
            success_rate_today=self._calculate_success_rate(
                totals.completed_today,
                totals.due_today,
            ),
            success_rate_7d=self._calculate_period_success_rate(
                habits=habits,
                completion_dates_by_habit=completion_dates_by_habit,
                period_start=self._period_start(today, 7),
                period_end=today,
                respect_archive=False,
            ),
            success_rate_30d=self._calculate_period_success_rate(
                habits=habits,
                completion_dates_by_habit=completion_dates_by_habit,
                period_start=self._period_start(today, 30),
                period_end=today,
                respect_archive=False,
            ),
            success_rate_90d=self._calculate_period_success_rate(
                habits=habits,
                completion_dates_by_habit=completion_dates_by_habit,
                period_start=self._period_start(today, 90),
                period_end=today,
                respect_archive=False,
            ),
            success_rate_all=self._calculate_period_success_rate(
                habits=habits,
                completion_dates_by_habit=completion_dates_by_habit,
                period_start=all_time_start,
                period_end=today,
                respect_archive=False,
            ),
            schedule_type_distribution={
                SCHEDULE_TYPE_LABELS[schedule_type]: count
                for schedule_type, count in totals.schedule_type_counts.items()
                if count > 0
            },
            completions_by_day=completions_by_period,
            top_streaks=[
                StatsBreakdownItem(label=name, value=streak)
                for streak, name, _, _ in sorted(
                    totals.streak_candidates,
                    key=lambda item: (
                        -item[0],
                        item[1].lower(),
                        item[2],
                        str(item[3]),
                    ),
                )[:TOP_LIST_LIMIT]
            ],
            top_themes=[
                StatsBreakdownItem(label=label, value=value)
                for label, value in sorted(
                    totals.top_theme_counts.items(),
                    key=lambda item: (-item[1], item[0].lower()),
                )[:TOP_LIST_LIMIT]
            ],
        )

    def _initialize_trend_buckets(
        self, selected_range: StatsRange, all_time_start: date, today: date
    ) -> _TrendBuckets:
        if selected_range == "all":
            return _TrendBuckets(
                start=all_time_start,
                monthly_counts=dict.fromkeys(
                    self._iter_period_months(all_time_start, today), 0
                ),
            )

        period_days = {"7d": 7, "30d": 30, "90d": 90}[selected_range]
        trend_start = self._period_start(today, period_days)

        if selected_range == "90d":
            return _TrendBuckets(
                start=trend_start,
                weekly_counts=dict.fromkeys(
                    self._iter_period_weeks(trend_start, today), 0
                ),
            )

        return _TrendBuckets(
            start=trend_start,
            daily_counts=dict.fromkeys(self._iter_period_dates(trend_start, today), 0),
        )

    def _populate_trend_buckets(
        self,
        *,
        completion_dates_by_habit: dict[UUID, set[date]],
        trend_buckets: _TrendBuckets,
        today: date,
    ) -> None:
        for completion_dates in completion_dates_by_habit.values():
            for completed_on in completion_dates:
                if trend_buckets.start <= completed_on <= today:
                    self._increment_trend_bucket(trend_buckets, completed_on)

    def _increment_trend_bucket(
        self,
        trend_buckets: _TrendBuckets,
        completed_on: date,
    ) -> None:
        if trend_buckets.monthly_counts is not None:
            trend_buckets.monthly_counts[(completed_on.year, completed_on.month)] += 1
            return

        if trend_buckets.weekly_counts is not None:
            for week_start, week_end in trend_buckets.weekly_counts:
                if week_start <= completed_on <= week_end:
                    trend_buckets.weekly_counts[(week_start, week_end)] += 1
                    return
            return

        if trend_buckets.daily_counts is not None:
            trend_buckets.daily_counts[completed_on] += 1

    async def _collect_page_statistics_totals(
        self,
        *,
        active_habits: list[HabitInDB],
        completion_dates_by_habit: dict[UUID, set[date]],
        today: date,
        themes_by_id: dict[UUID, ThemeInDB],
    ) -> _PageStatisticsTotals:
        totals = _PageStatisticsTotals(
            due_today=0,
            completed_today=0,
            schedule_type_counts=dict.fromkeys(SCHEDULE_TYPE_LABELS, 0),
            top_theme_counts={},
            streak_candidates=[],
        )

        for habit in active_habits:
            completion_dates = completion_dates_by_habit[habit.id]
            totals.schedule_type_counts[habit.schedule_type] += 1

            is_completed_today = today in completion_dates
            if is_completed_today:
                totals.completed_today += 1

            if is_completed_today or self._is_habit_due_today(
                habit,
                today=today,
                completion_dates=completion_dates,
                completed_today=is_completed_today,
            ):
                totals.due_today += 1

            streak = await self._calculate_streak(
                habit,
                completion_dates=completion_dates,
                reference_date=today,
            )
            if streak > 0:
                totals.streak_candidates.append(
                    (
                        streak,
                        habit.name,
                        self._to_utc_datetime(habit.created_at),
                        habit.id,
                    )
                )

            theme = themes_by_id.get(habit.theme_id) if habit.theme_id else None
            theme_label = theme.name if theme is not None else NO_THEME_LABEL
            totals.top_theme_counts[theme_label] = (
                totals.top_theme_counts.get(theme_label, 0) + 1
            )

        return totals

    def _build_completion_breakdown(
        self, trend_buckets: _TrendBuckets
    ) -> list[StatsBreakdownItem]:
        if trend_buckets.monthly_counts is not None:
            return [
                StatsBreakdownItem(
                    label=f"{month:02d}.{str(year)[-2:]}",
                    value=value,
                )
                for (year, month), value in trend_buckets.monthly_counts.items()
            ]

        if trend_buckets.weekly_counts is not None:
            return [
                StatsBreakdownItem(
                    label=f"{week_start:%d.%m}-{week_end:%d.%m}",
                    value=value,
                )
                for (week_start, week_end), value in trend_buckets.weekly_counts.items()
            ]

        if trend_buckets.daily_counts is None:
            return []

        return [
            StatsBreakdownItem(
                label=current_day.strftime("%d.%m"),
                value=value,
            )
            for current_day, value in trend_buckets.daily_counts.items()
        ]

    async def _get_completion_dates_by_habit(
        self, habits: list[HabitInDB]
    ) -> dict[UUID, set[date]]:
        habit_ids = [habit.id for habit in habits]
        completion_dates_by_habit = (
            await self.habit_repo.list_completion_dates_by_habit(habit_ids)
        )
        return {
            habit.id: set(completion_dates_by_habit.get(habit.id, set()))
            for habit in habits
        }

    async def _get_themes_by_habit(
        self, habits: list[HabitInDB]
    ) -> dict[UUID, ThemeInDB]:
        theme_ids = [habit.theme_id for habit in habits if habit.theme_id is not None]
        if not theme_ids:
            return {}

        return await self.theme_repo.list_by_ids(theme_ids)

    def _calculate_progress_percent(
        self, habit: HabitInDB, completion_dates: set[date], today: date
    ) -> float:
        if habit.ends_on is None:
            return 0.0

        period_start = habit.starts_on or habit.created_at.date()
        period_end = habit.ends_on
        if period_end < period_start:
            return 0.0

        required_total = self._required_occurrences_in_period(
            schedule_type=habit.schedule_type,
            schedule_config=habit.schedule_config,
            period_start=period_start,
            period_end=period_end,
        )
        if required_total <= 0:
            return 0.0

        completed_count = sum(
            1
            for completed_on in completion_dates
            if period_start <= completed_on <= period_end and completed_on <= today
        )
        progress = (completed_count / required_total) * 100
        return round(max(0.0, min(100.0, progress)), 2)

    def _required_occurrences_in_period(
        self,
        *,
        schedule_type: str,
        schedule_config: dict[str, object],
        period_start: date,
        period_end: date,
    ) -> int:
        if schedule_type == "daily":
            return (period_end - period_start).days + 1

        if schedule_type == "weekly_days":
            days = self._weekday_indexes(schedule_config["days"])
            return sum(
                1
                for day_offset in range((period_end - period_start).days + 1)
                if (period_start + timedelta(days=day_offset)).weekday() in days
            )

        if schedule_type == "monthly_day":
            return self._count_monthly_day_occurrences(
                period_start,
                period_end,
                self._get_int_config(schedule_config, "day"),
            )

        if schedule_type == "yearly_date":
            return self._count_yearly_date_occurrences(
                period_start,
                period_end,
                self._get_int_config(schedule_config, "month"),
                self._get_int_config(schedule_config, "day"),
            )

        if schedule_type == "interval_cycle":
            return self._count_interval_cycle_required(
                period_start,
                period_end,
                active_days=self._get_int_config(schedule_config, "active_days"),
                break_days=self._get_int_config(schedule_config, "break_days"),
            )

        return 0

    def _count_monthly_day_occurrences(
        self, period_start: date, period_end: date, target_day: int
    ) -> int:
        count = 0
        year, month = period_start.year, period_start.month
        end_year, end_month = period_end.year, period_end.month

        while (year, month) <= (end_year, end_month):
            current = self._monthly_expected_date(year, month, target_day)
            if period_start <= current <= period_end:
                count += 1
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return count

    def _count_yearly_date_occurrences(
        self, period_start: date, period_end: date, target_month: int, target_day: int
    ) -> int:
        count = 0
        for year in range(period_start.year, period_end.year + 1):
            current = self._yearly_expected_date(year, target_month, target_day)
            if period_start <= current <= period_end:
                count += 1
        return count

    def _count_interval_cycle_required(
        self,
        period_start: date,
        period_end: date,
        *,
        active_days: int,
        break_days: int,
    ) -> int:
        cycle_length = active_days + break_days
        return sum(
            1
            for day_offset in range((period_end - period_start).days + 1)
            if day_offset % cycle_length < active_days
        )

    def _period_start(self, period_end: date, days: int) -> date:
        return period_end - timedelta(days=days - 1)

    def _iter_period_dates(self, period_start: date, period_end: date) -> list[date]:
        return [
            period_start + timedelta(days=day_offset)
            for day_offset in range((period_end - period_start).days + 1)
        ]

    def _iter_period_months(
        self, period_start: date, period_end: date
    ) -> list[tuple[int, int]]:
        year = period_start.year
        month = period_start.month
        result: list[tuple[int, int]] = []

        while (year, month) <= (period_end.year, period_end.month):
            result.append((year, month))
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)

        return result

    def _iter_period_weeks(
        self, period_start: date, period_end: date
    ) -> list[tuple[date, date]]:
        result: list[tuple[date, date]] = []
        current_start = period_start

        while current_start <= period_end:
            current_end = min(current_start + timedelta(days=6), period_end)
            result.append((current_start, current_end))
            current_start = current_end + timedelta(days=1)

        return result

    def _all_time_period_start(
        self,
        habits: list[HabitInDB],
        completion_dates_by_habit: dict[UUID, set[date]],
        today: date,
    ) -> date:
        candidates = [self._schedule_anchor_date(habit) for habit in habits]
        candidates.extend(
            completed_on
            for completion_dates in completion_dates_by_habit.values()
            for completed_on in completion_dates
        )
        return min(candidates, default=today)

    def _calculate_success_rate(self, completed: int, due: int) -> int:
        return round((completed / due) * 100) if due else 0

    def _calculate_period_success_rate(
        self,
        *,
        habits: list[HabitInDB],
        completion_dates_by_habit: dict[UUID, set[date]],
        period_start: date,
        period_end: date,
        respect_archive: bool = True,
    ) -> int:
        due_occurrences = 0
        completed_occurrences = 0

        for habit in habits:
            completion_dates = completion_dates_by_habit.get(habit.id, set())
            for current_day in self._iter_period_dates(period_start, period_end):
                is_completed = current_day in completion_dates
                if is_completed or self._is_habit_due_today(
                    habit,
                    today=current_day,
                    completion_dates=completion_dates,
                    completed_today=is_completed,
                    respect_archive=respect_archive,
                ):
                    due_occurrences += 1
                    if is_completed:
                        completed_occurrences += 1

        return self._calculate_success_rate(completed_occurrences, due_occurrences)

    def _to_utc_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _resolve_reference_date(self, reference_time: datetime | None) -> date:
        if reference_time is None:
            return self._today_utc()
        return self._to_utc_datetime(reference_time).date()

    async def complete_habit(
        self, habit_id: UUID, completed_on: date | None = None
    ) -> HabitCompletionResult:
        today = self._today_utc()
        habit = await self.get_habit(habit_id)
        if not habit:
            raise HabitNotFound

        if habit.is_archived:
            raise ValueError("Cannot mark completion for archived habit")

        target_date = completed_on or today
        if target_date > today:
            raise ValueError("Cannot mark completion for a future date")

        completion_dates = await self.habit_repo.list_completion_dates(habit.id)
        if not self._is_habit_due_today(
            habit,
            today=target_date,
            completion_dates=completion_dates,
            completed_today=False,
        ):
            raise ValueError("Cannot mark completion for a non-scheduled date")

        changed = await self.habit_repo.add_completion(habit_id, target_date)
        completion_dates = await self.habit_repo.list_completion_dates(habit.id)
        new_streak = await self._calculate_streak(
            habit, completion_dates=completion_dates
        )
        return HabitCompletionResult(
            success=True,
            completed=True,
            date=target_date,
            new_streak=new_streak,
            changed=changed,
        )

    async def incomplete_habit(
        self, habit_id: UUID, completed_on: date | None = None
    ) -> HabitCompletionResult:
        today = self._today_utc()
        habit = await self.get_habit(habit_id)
        if not habit:
            raise HabitNotFound

        if habit.is_archived:
            raise ValueError("Cannot mark completion for archived habit")

        target_date = completed_on or today
        if target_date > today:
            raise ValueError("Cannot mark completion for a future date")

        changed = await self.habit_repo.remove_completion(habit_id, target_date)
        completion_dates = await self.habit_repo.list_completion_dates(habit.id)
        new_streak = await self._calculate_streak(
            habit, completion_dates=completion_dates
        )
        return HabitCompletionResult(
            success=True,
            completed=False,
            date=target_date,
            new_streak=new_streak,
            changed=changed,
        )

    async def _calculate_streak(
        self,
        habit: HabitInDB,
        completion_dates: set[date] | None = None,
        *,
        reference_date: date | None = None,
    ) -> int:
        completion_dates = (
            completion_dates
            if completion_dates is not None
            else await self.habit_repo.list_completion_dates(habit.id)
        )
        if not completion_dates:
            return 0

        schedule_type = habit.schedule_type
        schedule_config = habit.schedule_config
        reference_date = reference_date or self._today_utc()
        anchor_date = self._schedule_anchor_date(habit)
        if reference_date < anchor_date:
            return 0

        return self._streak_interval(
            completion_dates,
            schedule_type,
            schedule_config,
            reference_date,
            anchor_date,
        )

    def _streak_interval(
        self,
        completion_dates: set[date],
        schedule_type: Literal[
            "daily", "weekly_days", "monthly_day", "yearly_date", "interval_cycle"
        ],
        schedule_config: dict[str, object],
        reference_date: date,
        anchor_date: date,
    ) -> int:
        current = self._latest_expected_date(
            schedule_type, schedule_config, reference_date, anchor_date
        )
        streak = 0
        while current >= anchor_date and current in completion_dates:
            streak += 1
            current = self._previous_expected_date(
                schedule_type, schedule_config, current, anchor_date
            )
        return streak

    def _latest_expected_date(
        self,
        schedule_type: Literal[
            "daily", "weekly_days", "monthly_day", "yearly_date", "interval_cycle"
        ],
        schedule_config: dict[str, object],
        reference_date: date,
        anchor_date: date,
    ) -> date:
        if schedule_type == "daily":
            return reference_date

        if schedule_type == "weekly_days":
            days = self._weekday_indexes(schedule_config["days"])
            cursor = reference_date
            while cursor.weekday() not in days:
                cursor -= timedelta(days=1)
            return cursor

        if schedule_type == "monthly_day":
            target_day = self._get_int_config(schedule_config, "day")
            current = self._monthly_expected_date(
                reference_date.year, reference_date.month, target_day
            )
            if current <= reference_date:
                return current
            prev_year, prev_month = self._previous_month(
                reference_date.year, reference_date.month
            )
            return self._monthly_expected_date(prev_year, prev_month, target_day)

        if schedule_type == "interval_cycle":
            active_days = self._get_int_config(schedule_config, "active_days")
            break_days = self._get_int_config(schedule_config, "break_days")
            cycle_length = active_days + break_days
            elapsed = (reference_date - anchor_date).days
            phase = elapsed % cycle_length
            if phase < active_days:
                return reference_date
            skip_back = phase - active_days + 1
            return reference_date - timedelta(days=skip_back)

        target_month = self._get_int_config(schedule_config, "month")
        target_day = self._get_int_config(schedule_config, "day")
        current = self._yearly_expected_date(
            reference_date.year, target_month, target_day
        )
        if current <= reference_date:
            return current
        return self._yearly_expected_date(
            reference_date.year - 1, target_month, target_day
        )

    def _previous_expected_date(
        self,
        schedule_type: Literal[
            "daily", "weekly_days", "monthly_day", "yearly_date", "interval_cycle"
        ],
        schedule_config: dict[str, object],
        current_date: date,
        anchor_date: date,
    ) -> date:
        if schedule_type == "daily":
            return current_date - timedelta(days=1)

        if schedule_type == "weekly_days":
            days = self._weekday_indexes(schedule_config["days"])
            cursor = current_date - timedelta(days=1)
            while cursor.weekday() not in days:
                cursor -= timedelta(days=1)
            return cursor

        if schedule_type == "monthly_day":
            target_day = self._get_int_config(schedule_config, "day")
            year, month = self._previous_month(current_date.year, current_date.month)
            return self._monthly_expected_date(year, month, target_day)

        if schedule_type == "interval_cycle":
            active_days = self._get_int_config(schedule_config, "active_days")
            break_days = self._get_int_config(schedule_config, "break_days")
            phase = self._interval_phase(
                current_date,
                anchor_date=anchor_date,
                active_days=active_days,
                break_days=break_days,
            )
            if phase > 0:
                return current_date - timedelta(days=1)
            return current_date - timedelta(days=break_days + 1)

        target_month = self._get_int_config(schedule_config, "month")
        target_day = self._get_int_config(schedule_config, "day")
        return self._yearly_expected_date(
            current_date.year - 1, target_month, target_day
        )

    def _monthly_expected_date(self, year: int, month: int, day: int) -> date:
        month_last_day = monthrange(year, month)[1]
        return date(year, month, min(day, month_last_day))

    def _yearly_expected_date(self, year: int, month: int, day: int) -> date:
        month_last_day = monthrange(year, month)[1]
        return date(year, month, min(day, month_last_day))

    def _previous_month(self, year: int, month: int) -> tuple[int, int]:
        if month == 1:
            return year - 1, 12
        return year, month - 1

    def _weekday_indexes(self, days: object) -> set[int]:
        if not isinstance(days, list):
            raise ValueError("days must be list")
        result: set[int] = set()
        for day in days:
            if day not in WEEKDAY_ORDER:
                raise ValueError("days must contain only mon..sun")
            result.add(WEEKDAY_ORDER[cast(Weekday, day)])
        return result

    def _get_int_config(self, schedule_config: dict[str, object], key: str) -> int:
        value = schedule_config.get(key)
        if not isinstance(value, int):
            raise ValueError(f"{key} must be integer")
        return value

    def _schedule_anchor_date(self, habit: HabitInDB) -> date:
        return habit.starts_on or habit.created_at.date()

    def _interval_phase(
        self,
        value: date,
        *,
        anchor_date: date,
        active_days: int,
        break_days: int,
    ) -> int:
        cycle_length = active_days + break_days
        elapsed = (value - anchor_date).days
        return elapsed % cycle_length

    def _today_utc(self) -> date:
        return datetime.now(UTC).date()

    def _should_be_archived_by_interval(self, habit: HabitInDB, today: date) -> bool:
        return bool(habit.ends_on is not None and habit.ends_on < today)
