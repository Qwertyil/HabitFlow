from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import InDBBase


class TaskBase(BaseModel):
    name: str = Field(max_length=46, description="Название задачи, обязательное поле")
    description: str | None = Field(
        None,
        max_length=336,
        description="Подробное описание задачи (необязательное поле)",
    )
    theme_id: UUID | None = Field(
        None,
        description="Тема задачи"
        "Может быть действительным UUID темы"
        "либо строкой 'NoTheme' | пустым значением для обозначения отсутствия темы",
    )


class TaskCreate(TaskBase):
    priority_id: UUID = Field(
        description="Приоритет задачи ('low', 'medium' или 'high')",
    )

    @field_validator("theme_id", mode="before")
    @classmethod
    def validate_hex_color(cls, v: object) -> object:
        return TaskCreateAPI.empty_str_to_none(v)


class TaskCreateAPI(TaskBase):
    priority: str | UUID = Field(
        description="Приоритет задачи ('low', 'medium' или 'high') или в виде UUID",
    )

    @field_validator("theme_id", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if v == "NoTheme" or v == "00000000-0000-0000-0000-000000000001":
            return None
        return v


class TaskUpdate(BaseModel):
    name: str | None = Field(
        None, max_length=46, description="Название задачи, обязательное поле"
    )
    description: str | None = Field(
        None,
        max_length=336,
        description="Подробное описание задачи (необязательное поле)",
    )
    theme_id: UUID | None = None
    priority_id: UUID | None = None
    completed_at: datetime | None = None

    @field_validator("theme_id", mode="before")
    @classmethod
    def validate_hex_color(cls, v: object) -> object:
        return TaskCreateAPI.empty_str_to_none(v)


class TaskUpdateAPI(BaseModel):
    name: str | None = Field(
        None, max_length=46, description="Название задачи, обязательное поле"
    )
    description: str | None = Field(
        None,
        max_length=336,
        description="Подробное описание задачи (необязательное поле)",
    )
    theme_id: UUID | None = None
    priority: str | UUID | None = None
    completed_at: datetime | None = None

    @field_validator("theme_id", mode="before")
    @classmethod
    def validate_hex_color(cls, v: object) -> object:
        return TaskCreateAPI.empty_str_to_none(v)


class TaskInDB(TaskBase, InDBBase):
    priority_id: UUID
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


class TaskResponse(TaskBase, InDBBase):
    priority: str
    theme_name: str | None
    theme_color: str | None
    completed_at: datetime | None


class TaskMarkCompleted(BaseModel):
    success: bool
    completed: bool
    task: TaskInDB


class TaskStats(BaseModel):
    total: int
    completed: int
    pending: int
    by_priority: dict[str, int]
    by_theme: dict[str, int]
