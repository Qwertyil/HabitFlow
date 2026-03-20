from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from src.repositories import HabitRepository, ThemeRepository
from src.schemas.habits import HabitCreateAPI
from src.services.habits import HabitService
from tests.helpers import with_csrf_headers

WEEKDAY_BY_INDEX = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


async def mark_habit_as_completed(client, habit_id: UUID):
    return await client.patch(
        f"/habits/{habit_id}/complete",
        headers=await with_csrf_headers(client),
    )


@pytest.mark.asyncio
async def test_habits_list_status_filter_todays_active_and_completed(
    client, session, owner_id
):
    todays_id = await create_habit_and_return_id(
        session, owner_id=owner_id, name="habit-status-todays"
    )
    completed_id = await create_habit_and_return_id(
        session, owner_id=owner_id, name="habit-status-completed"
    )

    complete_response = await mark_habit_as_completed(client, completed_id)
    assert complete_response.status_code == 200

    todays_response = await client.get("/habits/?status=todays")
    assert todays_response.status_code == 200
    assert "habit-status-todays" in todays_response.text
    assert "habit-status-completed" not in todays_response.text

    active_response = await client.get("/habits/?status=active")
    assert active_response.status_code == 200
    assert "habit-status-todays" in active_response.text
    assert "habit-status-completed" in active_response.text

    completed_response = await client.get("/habits/?status=completed")
    assert completed_response.status_code == 200
    assert "habit-status-todays" not in completed_response.text
    assert "habit-status-completed" in completed_response.text

    completed_habit = await HabitRepository(
        session=session, owner_id=owner_id
    ).get_by_id(completed_id)
    assert completed_habit is not None
    assert completed_habit.is_archived is False

    todays_habit = await HabitRepository(session=session, owner_id=owner_id).get_by_id(
        todays_id
    )
    assert todays_habit is not None
    assert todays_habit.is_archived is False


@pytest.mark.asyncio
async def test_habit_moves_to_archive_when_period_is_over(client, session, owner_id):
    today = datetime.now(UTC).date()
    expired_id = await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="habit-expired-archived",
        starts_on=today - timedelta(days=14),
        ends_on=today - timedelta(days=1),
    )

    active_response = await client.get("/habits/?status=active")
    assert active_response.status_code == 200
    assert "habit-expired-archived" not in active_response.text

    archived_response = await client.get("/habits/?status=archived")
    assert archived_response.status_code == 200
    assert "habit-expired-archived" in archived_response.text

    expired_habit = await HabitRepository(session=session, owner_id=owner_id).get_by_id(
        expired_id
    )
    assert expired_habit is not None
    assert expired_habit.is_archived is True


@pytest.mark.asyncio
async def test_completed_status_excludes_archived_habits(client, session, owner_id):
    today = datetime.now(UTC).date()
    archived_id = await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="habit-archived-not-completed-filter",
        starts_on=today - timedelta(days=5),
        ends_on=today - timedelta(days=1),
    )

    habit_repo = HabitRepository(session=session, owner_id=owner_id)
    await habit_repo.add_completion(archived_id, today)
    await session.commit()

    completed_response = await client.get("/habits/?status=completed")
    assert completed_response.status_code == 200
    assert "habit-archived-not-completed-filter" not in completed_response.text

    archived_response = await client.get("/habits/?status=archived")
    assert archived_response.status_code == 200
    assert "habit-archived-not-completed-filter" in archived_response.text


@pytest.mark.asyncio
async def test_todays_status_filters_habits_by_schedule_for_current_date(
    client, session, owner_id
):
    today = datetime.now(UTC).date()
    today_weekday = WEEKDAY_BY_INDEX[today.weekday()]
    other_weekday = WEEKDAY_BY_INDEX[(today.weekday() + 1) % 7]
    monthly_not_today = 1 if today.day != 1 else 2
    yearly_month, yearly_day = (1, 1) if (today.month, today.day) != (1, 1) else (1, 2)

    await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="habit-daily-due-today",
        schedule_type="daily",
        schedule_config={},
    )
    await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="habit-weekly-not-today",
        schedule_type="weekly_days",
        schedule_config={"days": [other_weekday]},
    )
    await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="habit-weekly-due-today",
        schedule_type="weekly_days",
        schedule_config={"days": [today_weekday]},
    )
    await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="habit-monthly-not-today",
        schedule_type="monthly_day",
        schedule_config={"day": monthly_not_today},
    )
    await create_habit_and_return_id(
        session,
        owner_id=owner_id,
        name="habit-yearly-not-today",
        schedule_type="yearly_date",
        schedule_config={"month": yearly_month, "day": yearly_day},
    )

    response = await client.get("/habits/?status=todays")
    assert response.status_code == 200
    assert "habit-daily-due-today" in response.text
    assert "habit-weekly-due-today" in response.text
    assert "habit-weekly-not-today" not in response.text
    assert "habit-monthly-not-today" not in response.text
    assert "habit-yearly-not-today" not in response.text


@pytest.mark.asyncio
async def test_habit_owner_scope_hides_foreign_habit_and_blocks_mutations(
    client, secondary_client, session, secondary_owner_id
):
    foreign_habit_name = "habit-owned-by-user-b"
    foreign_habit_id = await create_habit_and_return_id(
        session,
        owner_id=secondary_owner_id,
        name=foreign_habit_name,
        schedule_type="daily",
        schedule_config={},
    )

    list_response = await client.get("/habits/?status=active")
    assert list_response.status_code == 200
    assert foreign_habit_name not in list_response.text

    detail_response = await client.get(f"/habits/{foreign_habit_id}")
    assert detail_response.status_code == 404
    assert "Привычка не найдена" in detail_response.text

    update_response = await client.put(
        f"/habits/{foreign_habit_id}",
        json={"name": "habit-overwritten-by-user-a"},
        headers=await with_csrf_headers(client),
    )
    assert update_response.status_code == 404
    assert update_response.json()["error"]["code"] == "not_found"

    complete_response = await mark_habit_as_completed(client, foreign_habit_id)
    assert complete_response.status_code == 404

    delete_response = await client.delete(
        f"/habits/{foreign_habit_id}",
        headers=await with_csrf_headers(client),
    )
    assert delete_response.status_code == 404

    owner_detail_response = await secondary_client.get(f"/habits/{foreign_habit_id}")
    assert owner_detail_response.status_code == 200
    assert foreign_habit_name in owner_detail_response.text

    foreign_habit = await HabitRepository(
        session=session,
        owner_id=secondary_owner_id,
    ).get_by_id(foreign_habit_id)
    assert foreign_habit is not None
    assert foreign_habit.name == foreign_habit_name
    assert await HabitRepository(
        session=session,
        owner_id=secondary_owner_id,
    ).list_completion_dates(foreign_habit_id) == set()


@pytest.mark.asyncio
async def test_habit_repository_with_missing_owner_is_fail_closed(session, owner_id):
    from src.schemas.habits import HabitCreate

    today = datetime.now(UTC).date()
    owner_repo = HabitRepository(session=session, owner_id=owner_id)
    habit = await owner_repo.add(
        HabitCreate(
            name="habit-owned-by-user",
            description=None,
            theme_id=None,
            schedule_type="daily",
            schedule_config={},
            starts_on=today - timedelta(days=2),
            ends_on=today - timedelta(days=1),
        )
    )
    await session.commit()

    guest_repo = HabitRepository(session=session, owner_id=None)

    guest_habit = await guest_repo.get_by_id(habit.id)
    habits, total = await guest_repo.list_habits(
        skip=0,
        limit=20,
        theme_id=None,
        today=today,
        status="active",
        schedule_type="all",
        sort="created_at",
        order="desc",
    )
    archived_count = await guest_repo.archive_expired_habits(today)

    assert guest_habit is None
    assert habits == []
    assert total == 0
    assert archived_count == 0

    owner_habit = await owner_repo.get_by_id(habit.id)
    assert owner_habit is not None
    assert owner_habit.is_archived is False


async def create_habit_and_return_id(
    session,
    *,
    owner_id: UUID,
    name: str,
    schedule_type="daily",
    schedule_config=None,
    theme_id=None,
    starts_on=None,
    ends_on=None,
):
    habit_repo = HabitRepository(session=session, owner_id=owner_id)
    theme_repo = ThemeRepository(session=session, owner_id=owner_id)
    habit_service = HabitService(habit_repo=habit_repo, theme_repo=theme_repo)

    habit = await habit_service.create_habit(
        HabitCreateAPI(
            name=name,
            theme_id=theme_id,
            schedule_type=schedule_type,
            schedule_config=schedule_config if schedule_config is not None else {},
            starts_on=starts_on,
            ends_on=ends_on,
        )
    )
    await session.commit()
    return habit.id
