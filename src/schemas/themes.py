import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .base import InDBBase


class ThemeBase(BaseModel):
    name: str = Field(
        ..., max_length=24, description="Название темы (максимум 24 символа)"
    )


class ThemeCreate(ThemeBase):
    color: str | None = Field(
        None,
        min_length=7,
        max_length=7,
        description="Цвет в формате HEX (#RRGGBB) или 'randoms' для случайного цвета",
    )

    @field_validator("color")
    @classmethod
    def validate_hex_color(cls, v: str | None) -> str | None:
        """
        Валидатор для проверки корректности HEX-цвета.
        """
        if not v or v == "randoms":
            return None

        hex_color_pattern = re.compile(r"^#([A-Fa-f0-9]{6})$")
        if not hex_color_pattern.match(v):
            raise ValueError(
                "Некорректный формат цвета. Используйте HEX-формат: #RRGGBB\n"
                "Примеры: #FF5733, #33FF57, #3357FF"
            )

        return v.upper()


class ThemeUpdate(BaseModel):
    name: str | None = Field(
        None, max_length=24, description="Название темы (максимум 24 символов)"
    )
    color: str | None = Field(
        None,
        min_length=7,
        max_length=7,
        description="Цвет в формате HEX (#RRGGBB) или 'randoms' для случайного цвета",
    )

    @field_validator("color")
    @classmethod
    def validate_hex_color(cls, v: str | None) -> str | None:
        return ThemeCreate.validate_hex_color(v)


class ThemeInDB(ThemeBase, InDBBase):
    color: str = Field(
        ..., min_length=7, max_length=7, description="Цвет в формате HEX (#RRGGBB)"
    )
    model_config = ConfigDict(from_attributes=True)


class ThemeResponse(ThemeBase):
    id: UUID
    color: str = Field(
        ..., min_length=7, max_length=7, description="Цвет в формате HEX (#RRGGBB)"
    )
    is_active: bool = Field(False)


class ThemeWithCountResponse(ThemeResponse):
    tasks_count: int
    habits_count: int
