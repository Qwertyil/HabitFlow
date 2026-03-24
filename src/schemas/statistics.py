from typing import Literal

from pydantic import BaseModel, Field

StatsRange = Literal["7d", "30d", "90d", "all"]


class StatsKpi(BaseModel):
    key: str
    label: str
    value: str | int | float
    hint: str | None = None


class StatsBreakdownItem(BaseModel):
    label: str
    value: int | float


class TaskStatisticsPage(BaseModel):
    total: int = 0
    active: int = 0
    completed: int = 0
    completion_rate: int = 0
    by_priority: dict[str, int] = Field(default_factory=dict)
    by_theme: dict[str, int] = Field(default_factory=dict)
    created_in_7d: int = 0
    created_in_30d: int = 0
    created_in_90d: int = 0
    completed_in_7d: int = 0
    completed_in_30d: int = 0
    completed_in_90d: int = 0
    avg_completion_time_hours: float | None = None


class HabitStatisticsPage(BaseModel):
    total: int = 0
    active: int = 0
    archived: int = 0
    due_today: int = 0
    completed_today: int = 0
    success_rate_today: int = 0
    success_rate_7d: int = 0
    success_rate_30d: int = 0
    success_rate_90d: int = 0
    success_rate_all: int = 0
    schedule_type_distribution: dict[str, int] = Field(default_factory=dict)
    completions_by_day: list[StatsBreakdownItem] = Field(default_factory=list)
    top_streaks: list[StatsBreakdownItem] = Field(default_factory=list)
    top_themes: list[StatsBreakdownItem] = Field(default_factory=list)


class ThemeStatisticsPage(BaseModel):
    top_task_themes: list[StatsBreakdownItem] = Field(default_factory=list)
    top_habit_themes: list[StatsBreakdownItem] = Field(default_factory=list)
    busiest_theme: StatsBreakdownItem | None = None


class StatsInsight(BaseModel):
    title: str
    description: str
    severity: Literal["info", "success", "warning"] = "info"


class StatisticsPageData(BaseModel):
    range: StatsRange
    kpis: list[StatsKpi] = Field(default_factory=list)
    tasks: TaskStatisticsPage = Field(default_factory=TaskStatisticsPage)
    habits: HabitStatisticsPage = Field(default_factory=HabitStatisticsPage)
    themes: ThemeStatisticsPage = Field(default_factory=ThemeStatisticsPage)
    insights: list[StatsInsight] = Field(default_factory=list)
