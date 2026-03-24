from __future__ import annotations

import unicodedata


def validate_user_facing_name(
    value: str,
    *,
    field_label: str = "Название",
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_label} должно быть строкой.")

    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_label} не может быть пустым.")

    if any(unicodedata.category(char).startswith("C") for char in normalized):
        raise ValueError(f"{field_label} содержит недопустимые управляющие символы.")

    return normalized
