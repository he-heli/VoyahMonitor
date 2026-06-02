from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from voyah_monitor.bot_ui import (
    BTN_ALERTS,
    BTN_BRIEF,
    BTN_FULL,
    BTN_LOCATION,
    BTN_SETTINGS,
    BTN_SNAPSHOT,
    MENU_BUTTONS,
    PLACEHOLDER_ALERTS,
    PLACEHOLDER_SETTINGS,
    main_menu_keyboard,
    split_telegram_messages,
    yandex_maps_keyboard,
)
from voyah_monitor.config import Settings
from voyah_monitor.scheduling import next_poll_delay_seconds
from voyah_monitor.session_manager import SessionExpiredError
from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import dashboard_items_to_telemetry
from voyah_monitor.vehicle_status import (
    extract_vehicle_coordinates,
    format_dashboard_brief,
    format_dashboard_status,
    vehicle_location_title,
)
from voyah_monitor.voyah_api import VoyahReadOnlyApi

logger = logging.getLogger(__name__)

MENU_HINT = "Используйте кнопки меню ниже."


def _authorized(settings: Settings, user_id: int) -> bool:
    allowed = settings.telegram_user_ids
    return not allowed or user_id in allowed


def _fetch_dashboard(settings: Settings) -> list[dict[str, Any]]:
    with VoyahReadOnlyApi(settings) as api:
        return api.fetch_dashboard_status()


def _fetch_and_save(settings: Settings, storage: TelemetryStorage) -> list:
    items = _fetch_dashboard(settings)
    telemetries = dashboard_items_to_telemetry(items)
    for telemetry in telemetries:
        storage.save_snapshot(telemetry)
    return telemetries


async def _send_menu(message: Message, text: str) -> None:
    await message.answer(text, reply_markup=main_menu_keyboard())


async def _send_long_text(message: Message, text: str) -> None:
    parts = split_telegram_messages(text)
    for index, part in enumerate(parts):
        if index == len(parts) - 1:
            await message.answer(part, reply_markup=main_menu_keyboard())
        else:
            await message.answer(part)


def create_dispatcher(settings: Settings, storage: TelemetryStorage) -> Dispatcher:
    dp = Dispatcher()

    async def _guard(message: Message) -> bool:
        if _authorized(settings, message.from_user.id):
            return True
        await message.answer("Доступ запрещен.")
        return False

    @dp.message(Command("start", "help", "menu"))
    async def cmd_menu(message: Message) -> None:
        if not await _guard(message):
            return
        hours = settings.telegram_poll_interval // 3600
        jitter_pct = int(settings.telegram_poll_jitter * 100)
        await _send_menu(
            message,
            "VOYAH Monitor\n\n"
            f"Фоновый сбор в базу: ~каждые {hours} ч (±{jitter_pct}%)\n"
            "Актуальные данные — по кнопкам «Полная» / «Краткая» / «Найти машину».\n\n"
            + MENU_HINT,
        )

    @dp.message(Command("status"))
    async def cmd_status_alias(message: Message) -> None:
        await on_full_info(message)

    @dp.message(Command("collect"))
    async def cmd_collect_alias(message: Message) -> None:
        await on_snapshot(message)

    @dp.message(F.text == BTN_FULL)
    async def on_full_info(message: Message) -> None:
        if not await _guard(message):
            return
        await message.answer("Загружаю полную информацию (read-only)...", reply_markup=main_menu_keyboard())
        try:
            items = await asyncio.to_thread(_fetch_dashboard, settings)
        except SessionExpiredError as exc:
            await message.answer(str(exc), reply_markup=main_menu_keyboard())
            return
        except Exception as exc:
            await message.answer(f"Ошибка: {exc}", reply_markup=main_menu_keyboard())
            return
        if not items:
            await message.answer("Автомобили не найдены.", reply_markup=main_menu_keyboard())
            return
        await _send_long_text(message, format_dashboard_status(items))

    @dp.message(F.text == BTN_BRIEF)
    async def on_brief_info(message: Message) -> None:
        if not await _guard(message):
            return
        await message.answer("Загружаю краткую сводку...", reply_markup=main_menu_keyboard())
        try:
            items = await asyncio.to_thread(_fetch_dashboard, settings)
        except SessionExpiredError as exc:
            await message.answer(str(exc), reply_markup=main_menu_keyboard())
            return
        except Exception as exc:
            await message.answer(f"Ошибка: {exc}", reply_markup=main_menu_keyboard())
            return
        if not items:
            await message.answer("Автомобили не найдены.", reply_markup=main_menu_keyboard())
            return
        await _send_long_text(message, format_dashboard_brief(items))

    @dp.message(F.text == BTN_LOCATION)
    async def on_find_car(message: Message) -> None:
        if not await _guard(message):
            return
        await message.answer("Определяю местоположение...", reply_markup=main_menu_keyboard())
        try:
            items = await asyncio.to_thread(_fetch_dashboard, settings)
        except SessionExpiredError as exc:
            await message.answer(str(exc), reply_markup=main_menu_keyboard())
            return
        except Exception as exc:
            await message.answer(f"Ошибка: {exc}", reply_markup=main_menu_keyboard())
            return
        if not items:
            await message.answer("Автомобили не найдены.", reply_markup=main_menu_keyboard())
            return

        sent = False
        for item in items:
            coords = extract_vehicle_coordinates(item)
            title = vehicle_location_title(item)
            if not coords:
                await message.answer(
                    f"{title}: геопозиция недоступна.",
                    reply_markup=main_menu_keyboard(),
                )
                continue
            lat, lon = coords
            await message.answer_location(latitude=lat, longitude=lon)
            await message.answer(
                f"{title}\n{lat:.5f}, {lon:.5f}",
                reply_markup=yandex_maps_keyboard(lat, lon),
            )
            sent = True

        if sent:
            await message.answer("Точка на карте отправлена.", reply_markup=main_menu_keyboard())

    @dp.message(F.text == BTN_SNAPSHOT)
    async def on_snapshot(message: Message) -> None:
        if not await _guard(message):
            return
        await message.answer("Сохраняю снимок в базу (read-only)...", reply_markup=main_menu_keyboard())
        try:
            telemetries = await asyncio.to_thread(_fetch_and_save, settings, storage)
        except SessionExpiredError as exc:
            await message.answer(str(exc), reply_markup=main_menu_keyboard())
            return
        except Exception as exc:
            await message.answer(f"Ошибка: {exc}", reply_markup=main_menu_keyboard())
            return
        if telemetries:
            await message.answer(
                f"Снимок сохранён: {len(telemetries)} запись(ей).\n"
                f"Всего в базе: {storage.snapshot_count()} снимков.",
                reply_markup=main_menu_keyboard(),
            )
        else:
            await message.answer("Автомобили не найдены.", reply_markup=main_menu_keyboard())

    @dp.message(F.text == BTN_SETTINGS)
    async def on_settings(message: Message) -> None:
        if not await _guard(message):
            return
        await _send_menu(message, PLACEHOLDER_SETTINGS)

    @dp.message(F.text == BTN_ALERTS)
    async def on_alerts(message: Message) -> None:
        if not await _guard(message):
            return
        await _send_menu(message, PLACEHOLDER_ALERTS)

    @dp.message(F.text)
    async def fallback(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            return
        if message.text in MENU_BUTTONS:
            return
        await _send_menu(message, f"Неизвестная команда.\n\n{MENU_HINT}")

    return dp


async def run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    storage = TelemetryStorage(settings.voyah_db_path)
    bot = Bot(token=settings.telegram_bot_token)
    dp = create_dispatcher(settings, storage)

    async def periodic_collect() -> None:
        base = settings.telegram_poll_interval
        jitter = settings.telegram_poll_jitter
        logger.info(
            "Background telemetry collection ~every %.1f h (±%.0f%%)",
            base / 3600,
            jitter * 100,
        )
        while True:
            delay = next_poll_delay_seconds(base, jitter)
            logger.info("Next background collect in %.0f min", delay / 60)
            await asyncio.sleep(delay)
            try:
                await asyncio.to_thread(_fetch_and_save, settings, storage)
            except Exception:
                logger.exception("Periodic telemetry collection failed")

    logger.info("Starting Telegram bot...")
    asyncio.create_task(periodic_collect())
    await dp.start_polling(bot)
