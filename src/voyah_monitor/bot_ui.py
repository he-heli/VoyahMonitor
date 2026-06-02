from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# --- Main menu (reply keyboard) ---

BTN_FULL = "Полная информация"
BTN_BRIEF = "Краткая информация"
BTN_SETTINGS = "Настройки"
BTN_ALERTS = "Контроль параметров"
BTN_LOCATION = "Найти машину"
BTN_SNAPSHOT = "Снимок в базу"

MENU_BUTTONS = frozenset(
    {
        BTN_FULL,
        BTN_BRIEF,
        BTN_SETTINGS,
        BTN_ALERTS,
        BTN_LOCATION,
        BTN_SNAPSHOT,
    }
)

PLACEHOLDER_SETTINGS = (
    "Раздел «Настройки» пока пуст.\n\n"
    "Позже: интервал фонового опроса, список получателей уведомлений."
)

PLACEHOLDER_ALERTS = (
    "Раздел «Контроль параметров» пока пуст.\n\n"
    "Позже: пороги заряда, offline, пробег за день и push при изменениях."
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_FULL), KeyboardButton(text=BTN_BRIEF)],
            [KeyboardButton(text=BTN_LOCATION), KeyboardButton(text=BTN_SNAPSHOT)],
            [KeyboardButton(text=BTN_SETTINGS), KeyboardButton(text=BTN_ALERTS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие",
    )


def yandex_maps_keyboard(lat: float, lon: float) -> InlineKeyboardMarkup:
    url = yandex_maps_url(lat, lon)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть в Яндекс.Картах", url=url)],
        ]
    )


def yandex_maps_url(lat: float, lon: float) -> str:
    """Yandex Maps expects lon,lat in the pt query parameter."""
    return f"https://yandex.ru/maps/?pt={lon},{lat}&z=16&l=map"


def split_telegram_messages(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in text.split("\n\n"):
        extra = 2 if current else 0
        if len(block) + extra > limit:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            for start in range(0, len(block), limit):
                chunks.append(block[start : start + limit])
            continue

        if current_len + len(block) + extra > limit:
            chunks.append("\n\n".join(current))
            current = [block]
            current_len = len(block)
        else:
            current.append(block)
            current_len += len(block) + extra

    if current:
        chunks.append("\n\n".join(current))
    return chunks
