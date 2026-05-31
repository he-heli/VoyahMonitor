from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from voyah_monitor.config import Settings
from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import format_status, dashboard_items_to_telemetry
from voyah_monitor.session_manager import SessionExpiredError
from voyah_monitor.voyah_api import VoyahReadOnlyApi

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
    try:
        telemetries = await asyncio.to_thread(_fetch_and_save, settings, storage)
    except SessionExpiredError as exc:
        return str(exc)
    except Exception as exc:
        return f"Не удалось получить телеметрию: {exc}"

    if telemetries:
        return f"Сохранено записей телеметрии: {len(telemetries)}"
    return "Автомобили не найдены."


def _fetch_and_save(settings: Settings, storage: TelemetryStorage) -> list:
    with VoyahReadOnlyApi(settings) as api:
        items = api.fetch_dashboard_status()
    telemetries = dashboard_items_to_telemetry(items)
    for telemetry in telemetries:
        storage.save_snapshot(telemetry)
    return telemetries


def create_dispatcher(settings: Settings, storage: TelemetryStorage) -> Dispatcher:
    dp = Dispatcher()

    @dp.message(Command("start", "help"))
    async def cmd_help(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        await message.answer(
            "Команды:\n"
            "/status — актуальное состояние (запрос к VOYAH)\n"
            "/collect — сохранить снимок в базу\n"
            "/mileage — график дневных пробегов\n"
            "/battery — история заряда\n"
            "/history — последний сохранённый снимок\n\n"
            f"Фоновое обновление: каждые {settings.telegram_poll_interval // 3600} ч."
        )

    @dp.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            await message.answer("Доступ запрещен.")
            return
        await message.answer("Запрашиваю актуальные данные (read-only)...")
        try:
            telemetries = await asyncio.to_thread(_fetch_and_save, settings, storage)
        except SessionExpiredError as exc:
            await message.answer(str(exc))
            return
        except Exception as exc:
            await message.answer(f"Не удалось получить телеметрию: {exc}")
            return
        if not telemetries:
            await message.answer("Автомобили не найдены.")
            return
        await message.answer("\n\n---\n\n".join(format_status(item) for item in telemetries))

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
        interval_hours = settings.telegram_poll_interval / 3600
        logger.info("Background telemetry collection every %.1f h", interval_hours)
        while True:
            await asyncio.sleep(settings.telegram_poll_interval)
            try:
                await asyncio.to_thread(_fetch_and_save, settings, storage)
            except Exception:
                logger.exception("Periodic telemetry collection failed")

    logger.info("Starting Telegram bot...")
    asyncio.create_task(periodic_collect())
    await dp.start_polling(bot)
