import hashlib
import random
from uuid import UUID

from src.repositories import ThemeRepository
from src.schemas import (
    ThemeCreate,
    ThemeInDB,
    ThemeResponse,
    ThemeUpdate,
    ThemeWithCountResponse,
)
from src.validation import validate_user_facing_name

THEME_COLORS = {
    "#34495E",
    "#2ECC71",
    "#E74C3C",
    "#1ABC9C",
    "#3498DB",
    "#9B59B6",
    "#F39C12",
    "#E67E22",
    "#E91E63",
    "#00BCD4",
    "#8BC34A",
}


class ThemeService:
    def __init__(self, theme_repo: ThemeRepository):
        self.theme_repo = theme_repo

    async def get_existing_colors(self) -> set[str]:
        return await self.theme_repo.get_existing_colors_list()

    async def create_theme(self, theme_data: ThemeCreate) -> ThemeInDB:
        validated_name = validate_user_facing_name(
            theme_data.name, field_label="Название темы"
        )
        existing_name = await self.theme_repo.get_by_name(validated_name)
        if existing_name:
            raise ValueError("Theme with this name already exists")

        if validated_name.lower() == "все темы":
            raise ValueError("Invalid theme title")

        if theme_data.color:
            existing_color = await self.theme_repo.get_by_color(theme_data.color)
            if existing_color:
                raise ValueError("Theme with this color already exists")
            color = theme_data.color
        else:
            color = await self.generate_color(validated_name)
        theme_data = ThemeCreate(name=validated_name, color=color)
        return await self.theme_repo.add(theme_data)

    async def get_theme_by_name(self, theme_name: str) -> ThemeInDB | None:
        return await self.theme_repo.get_by_name(theme_name)

    async def get_theme_by_id(self, theme_id: UUID) -> ThemeInDB | None:
        return await self.theme_repo.get_by_id(theme_id)

    async def update_theme(
        self, old_theme: ThemeInDB, theme_data: ThemeUpdate
    ) -> ThemeInDB | None:
        update_dict = theme_data.model_dump(exclude_unset=True)

        if not update_dict:
            return old_theme

        # --- Обработка имени ---
        if "name" in update_dict:
            new_name = validate_user_facing_name(
                update_dict["name"], field_label="Название темы"
            )
            update_dict["name"] = new_name
            if new_name != old_theme.name:
                existing = await self.theme_repo.get_by_name(new_name)
                if existing:
                    raise ValueError("Theme with this name already exists")
                if new_name.lower() == "все темы":
                    raise ValueError("Invalid theme title")
            # Имя остаётся в словаре для обновления

        # --- Обработка цвета ---
        if "color" in update_dict:
            new_color = update_dict["color"]  # после валидатора: None или HEX-строка

            if new_color is None:
                # Клиент передал "randoms" или null → генерируем случайный цвет
                # Используем итоговое имя (новое, если меняется, иначе старое)
                target_name = update_dict.get("name", old_theme.name)
                generated = await self.generate_color(target_name)
                update_dict["color"] = generated
            else:
                if new_color != old_theme.color:
                    existing = await self.theme_repo.get_by_color(new_color)
                    if existing:
                        raise ValueError("Theme with this color already exists")
                # Цвет остаётся как есть

        updated_theme = ThemeUpdate(**update_dict)
        return await self.theme_repo.update(old_theme.id, updated_theme)

    async def delete_theme(self, theme_id: UUID) -> bool:
        return await self.theme_repo.delete(theme_id)

    async def list_themes(
        self, skip: int = 0, limit: int | None = 100
    ) -> list[ThemeResponse]:
        """Получить список тем в формате словарей для контекста"""
        themes = await self.theme_repo.list(skip=skip, limit=limit)
        return [self._to_response(theme) for theme in themes]

    def _to_response(self, theme: ThemeInDB) -> ThemeResponse:
        """Приватный метод для преобразования"""
        return ThemeResponse(id=theme.id, name=theme.name, color=theme.color)

    async def generate_color(self, title: str) -> str:
        color = string_to_hex(title)
        existing_color = await self.theme_repo.get_by_color(color)
        if existing_color:
            for _ in range(10):
                color = generate_random_hex()
                existing_color = await self.theme_repo.get_by_color(color)
                if not existing_color:
                    break
            else:
                raise RuntimeError("Failed to generate a unique theme color")
        return color

    async def list_themes_with_counts(
        self, page: int = 1, per_page: int = 30
    ) -> tuple[list[ThemeWithCountResponse], int]:
        """
        Возвращает список тем с количеством задач и привычек в каждой.
        """
        skip = (page - 1) * per_page
        total = await self.theme_repo.count_themes()
        themes_with_counts = await self.theme_repo.list_with_counts(
            skip=skip, limit=per_page
        )
        items = [
            ThemeWithCountResponse(
                id=theme.id,
                name=theme.name,
                color=theme.color,
                tasks_count=tasks_count,
                habits_count=habits_count,
            )
            for theme, tasks_count, habits_count in themes_with_counts
        ]
        return items, total


def _hsl_to_hex(hue: int, saturation: int, lightness: int) -> str:
    c = (1 - abs(2 * lightness / 100 - 1)) * saturation / 100
    x = c * (1 - abs((hue / 60) % 2 - 1))
    m = lightness / 100 - c / 2

    if 0 <= hue < 60:
        r, g, b = c, x, 0.0
    elif 60 <= hue < 120:
        r, g, b = x, c, 0.0
    elif 120 <= hue < 180:
        r, g, b = 0.0, c, x
    elif 180 <= hue < 240:
        r, g, b = 0.0, x, c
    elif 240 <= hue < 300:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x

    r = int((r + m) * 255)
    g = int((g + m) * 255)
    b = int((b + m) * 255)

    return f"#{r:02x}{g:02x}{b:02x}"


def string_to_hex(title: str) -> str:
    hash_obj = hashlib.md5(title.strip().lower().encode())
    hash_int = int(hash_obj.hexdigest(), 16)
    hue = hash_int % 360
    saturation = 70
    lightness = 60
    return _hsl_to_hex(hue, saturation, lightness)


def generate_random_hex() -> str:
    hue = random.randint(0, 360)
    saturation = random.randint(60, 90)
    lightness = random.randint(40, 70)
    return _hsl_to_hex(hue, saturation, lightness)
