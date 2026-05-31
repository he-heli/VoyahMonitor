from __future__ import annotations

import asyncio
import logging
from typing import Callable

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from voyah_monitor.client import VoyahClient
from voyah_monitor.config import Settings
from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import format_status, normalize_payload

logger = logging.getLogger(__name__)


def _authorized(settings: Settings, user_id: int) -> bool:
    allowed = settings.telegram_user_ids
    return not allowed or user_id in allowed


def _render_mileage_chart(storage: TelemetryStorage, vehicle_key: str | None = None) -> str:
    rows = storage.daily_mileage(days=14, vehicle_key=vehicle_key)
    if not rows:
        return "Нет данных по дневным пробегам."

    rows = list(reversed(rows))
    max_distance = max(row.distance_km for row in rows) or 1.0
    lines = ["Дневной пробег (14 дней):"]
    for row in rows:
        bar_len = max(1, int((row.distance_km / max_distance) * 10)) if row.distance_km > 0 else 0
        bar = "#" * bar_len
        lines.append(f"{row.day.isoformat()} {row.distance_km:5.1f} km {bar}")
    return "\n".join(lines)


def _render_battery_chart(storage: TelemetryStorage, vehicle_key: str | None = None) -> str:
    points = storage.battery_history(days=7, vehicle_key=vehicle_key)
    if not points:
        return "Нет данных по заряду батареи."

    sampled = points[:: max(1, len(points) // 12)]
    lines = ["Заряд батареи (7 дней):"]
    for ts, value in sampled:
        lines.append(f"{ts.astimezone().strftime('%m-%d %H:%M')} {value:5.1f}%")
    return "\n".join(lines)


async def _collect_and_store(settings: Settings, storage: TelemetryStorage) -> str:
    with VoyahClient(settings) as client:
        payloads = client.fetch_all_allowed()

    saved = 0
    errors: list[str] = []
    for item in payloads:
        if "error" in item:
            errors.append(f"{item['method']} {item['path']}: {item['error']}")
            continue
        for telemetry in normalize_payload(item["data"]):
            storage.save_snapshot(telemetry)
            saved += 1

    if saved:
        return f"Сохранено записей телеметрии: {saved}"
    if errors:
        return "Не удалось получить телеметрию:\n" + "\n".join(errors[:5])
    return "Нет разрешенных endpoint-ов. Сначала выполните login и настройте allow-list."


def create_dispatcher(settings: Settings, storage: TelemetryStorage) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        await message.answer(
            "Команды:\n"
            "/status — текущее состояние\n"
            "/collect — обновить данные с VOYAH\n"
            "/mileage — график дневных пробегов\n"
            "/battery — история заряда\n"
            "/history — последние сохраненные данные"
        )

    @dp.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        latest = storage.latest_snapshot()
        if not latest:
            await message.answer("Данных пока нет. Выполните /collect после login.")
            return
        await message.answer(format_status(latest))

    @dp.message(Command("collect"))
    async def cmd_collect(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        await message.answer("Запрашиваю телеметрию (read-only)...")
        result = await asyncio.to_thread(_collect_and_store, settings, storage)
        await message.answer(result)

    @dp.message(Command("mileage"))
    async def cmd_mileage(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        await message.answer(_render_mileage_chart(storage))

    @dp.message(Command("battery"))
    async def cmd_battery(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        await message.answer(_render_battery_chart(storage))

    @dp.message(Command("history"))
    async def cmd_history(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        latest = storage.latest_snapshot()
        if not latest:
            await message.answer("История пуста.")
            return
        mileage = storage.daily_mileage(days=7)
        text = format_status(latest)
        if mileage:
            text += "\n\nПоследние дни:\n"
            for row in mileage[:7]:
                text += f"{row.day}: {row.distance_km:.1f} km\n"
        await message.answer(text)

    @dp.message(F.text)
    async def fallback(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            return
        await message.answer("Неизвестная команда. Используйте /help")

    return dp


async def run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    storage = TelemetryStorage(settings.voyah_db_path)
    bot = Bot(token=settings.telegram_bot_token)
    dp = create_dispatcher(settings, storage)

    async def periodic_collect() -> None:
        while True:
            try:
                await asyncio.to_thread(_collect_and_store, settings, storage)
            except Exception:
                logger.exception("Periodic telemetry collection failed")
            await asyncio.sleep(settings.telegram_poll_interval)

    logger.info("Starting Telegram bot...")
    asyncio.create_task(periodic_collect())
    await dp.start_polling(bot)
