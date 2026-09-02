from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message

from voyah_monitor.alert_settings import BotSettingsStore
from voyah_monitor.alerts import evaluate_alerts
from voyah_monitor.bot_ui import (
    BTN_ALERTS,
    BTN_BRIEF,
    BTN_FULL,
    BTN_HISTORY,
    BTN_LOCATION,
    BTN_MAIN,
    BTN_SETTINGS,
    BTN_SNAPSHOT,
    CB_ALERTS_BACK,
    CB_HISTORY_PREFIX,
    CB_NAV_MAIN,
    CB_ALERTS_CONNECT,
    CB_ALERTS_CONNECT_TOGGLE,
    CB_ALERTS_SOH,
    CB_ALERTS_SOH_TOGGLE,
    CB_ALERTS_CHARGE,
    CB_ALERTS_CHARGE_TOGGLE,
    CB_ALERTS_CHARGE_MAX_CUSTOM,
    CB_ALERTS_V12,
    CB_ALERTS_V12_TOGGLE,
    CB_POLL_PREFIX,
    MENU_BUTTONS,
    POLL_INTERVAL_VALUES,
    alerts_menu_keyboard,
    format_bot_status_text,
    format_history_menu_text,
    connect_alert_keyboard,
    charge_alert_keyboard,
    format_alerts_menu_text,
    format_charge_alert_text,
    format_connect_alert_text,
    format_poll_interval_label,
    format_settings_poll_text,
    format_soh_alert_text,
    format_v12_alert_text,
    history_period_keyboard,
    main_menu_keyboard,
    parse_history_callback_data,
    parse_poll_callback_data,
    parse_charge_max_callback,
    parse_charge_max_input,
    parse_charge_trigger_callback,
    parse_v12_threshold_callback,
    settings_poll_keyboard,
    split_telegram_messages,
    soh_alert_keyboard,
    v12_alert_keyboard,
    yandex_maps_keyboard,
)
from voyah_monitor.config import Settings
from voyah_monitor.history_export import export_filename, export_history_xlsx_to_path, period_label
from voyah_monitor.scheduling import next_poll_delay_seconds
from voyah_monitor.session_expiry import (
    REVOKED_MARKER,
    exp_key,
    format_session_expiry_message,
    format_session_revoked_message,
    load_refresh_expires_at,
    should_notify_session_expiry,
    should_notify_session_revoked,
)
from voyah_monitor.session_manager import SessionExpiredError
from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import VehicleTelemetry, dashboard_items_to_telemetry
from voyah_monitor.vehicle_status import (
    extract_vehicle_coordinates,
    format_dashboard_brief,
    format_dashboard_status,
    vehicle_location_title,
)
from voyah_monitor.voyah_api import VoyahReadOnlyApi

logger = logging.getLogger(__name__)

class BotRuntimeConfig:
    """Mutable bot preferences persisted in data/bot_settings.json."""

    def __init__(self, settings: Settings) -> None:
        self._store = BotSettingsStore(
            settings.voyah_db_path.parent / "bot_settings.json",
            default_poll_interval=settings.telegram_poll_interval,
        )
        if self._store.poll_interval not in POLL_INTERVAL_VALUES:
            self._store.poll_interval = settings.telegram_poll_interval
        self.awaiting_charge_max_input = False

    @property
    def poll_interval(self) -> int:
        return self._store.poll_interval

    @poll_interval.setter
    def poll_interval(self, value: int) -> None:
        self._store.poll_interval = value

    @property
    def alerts(self):
        return self._store.alerts

    @property
    def session_expiry_notified(self) -> dict[str, list[int]]:
        return self._store.session_expiry_notified

    def set_poll_interval(self, seconds: int) -> None:
        if seconds not in POLL_INTERVAL_VALUES:
            raise ValueError(f"unsupported poll interval: {seconds}")
        self.poll_interval = seconds

    def save(self) -> None:
        self._store.save()


def _authorized(settings: Settings, user_id: int) -> bool:
    allowed = settings.telegram_user_ids
    return not allowed or user_id in allowed


def _fetch_dashboard(settings: Settings) -> list[dict[str, Any]]:
    with VoyahReadOnlyApi(settings) as api:
        return api.fetch_dashboard_status()


def _fetch_and_save(settings: Settings, storage: TelemetryStorage) -> list[VehicleTelemetry]:
    items = _fetch_dashboard(settings)
    telemetries = dashboard_items_to_telemetry(items)
    for telemetry in telemetries:
        storage.save_snapshot(telemetry)
    return telemetries


async def _dispatch_session_revoked_alert(
    bot: Bot,
    settings: Settings,
    runtime: BotRuntimeConfig,
) -> None:
    """Notify once when VOYAH rejects refresh (even if JWT exp is still in the future)."""
    user_ids = settings.telegram_user_ids
    if not user_ids:
        return

    expires_at = await asyncio.to_thread(
        load_refresh_expires_at,
        settings.voyah_session_path,
        settings.voyah_base_url,
    )
    key = exp_key(expires_at) if expires_at is not None else "unknown"
    already = list(runtime.session_expiry_notified.get(key, []))
    if not should_notify_session_revoked(already):
        return

    text = format_session_revoked_message(expires_at=expires_at)
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
        except Exception:
            logger.exception(
                "Failed to send session-revoked alert to user %s",
                user_id,
            )

    already.append(REVOKED_MARKER)
    runtime.session_expiry_notified[key] = sorted(set(already))
    runtime.save()
    logger.info("Session-revoked alert sent (key=%s)", key)


async def _dispatch_session_expiry_reminders(
    bot: Bot,
    settings: Settings,
    runtime: BotRuntimeConfig,
) -> None:
    user_ids = settings.telegram_user_ids
    if not user_ids:
        return

    expires_at = await asyncio.to_thread(
        load_refresh_expires_at,
        settings.voyah_session_path,
        settings.voyah_base_url,
    )
    if expires_at is None:
        return

    key = exp_key(expires_at)
    already = list(runtime.session_expiry_notified.get(key, []))
    days_left = should_notify_session_expiry(
        expires_at=expires_at,
        notified_for_exp=already,
    )
    if days_left is None:
        return

    text = format_session_expiry_message(days_left, expires_at)
    for user_id in user_ids:
        try:
            await bot.send_message(user_id, text)
        except Exception:
            logger.exception(
                "Failed to send session expiry reminder (%s days) to user %s",
                days_left,
                user_id,
            )

    already.append(days_left)
    runtime.session_expiry_notified[key] = sorted(set(already))
    runtime.save()
    logger.info("Session expiry reminder sent: %s days left", days_left)


async def _dispatch_alert_notifications(
    bot: Bot,
    settings: Settings,
    runtime: BotRuntimeConfig,
    telemetries: list[VehicleTelemetry],
) -> None:
    user_ids = settings.telegram_user_ids
    if not user_ids or not telemetries:
        return

    for telemetry in telemetries:
        notifications, new_state = evaluate_alerts(telemetry, runtime.alerts)
        runtime.alerts.state = new_state
        for notification in notifications:
            for user_id in user_ids:
                try:
                    if notification.photo_png:
                        photo = BufferedInputFile(
                            notification.photo_png,
                            filename="charging.png",
                        )
                        await bot.send_photo(user_id, photo, caption=notification.text)
                    else:
                        await bot.send_message(user_id, notification.text)
                except Exception:
                    logger.exception(
                        "Failed to send alert %s to user %s",
                        notification.kind,
                        user_id,
                    )
    runtime.save()


async def _send_main_status(
    message: Message,
    runtime: BotRuntimeConfig,
    storage: TelemetryStorage,
    jitter: float,
) -> None:
    text = format_bot_status_text(
        snapshot_count=storage.snapshot_count(),
        poll_interval_seconds=runtime.poll_interval,
        jitter_fraction=jitter,
        alerts=runtime.alerts,
    )
    await message.answer(text, reply_markup=main_menu_keyboard())


async def _send_long_text(message: Message, text: str) -> None:
    parts = split_telegram_messages(text)
    for index, part in enumerate(parts):
        if index == len(parts) - 1:
            await message.answer(part, reply_markup=main_menu_keyboard())
        else:
            await message.answer(part)


async def _send_settings(message: Message, runtime: BotRuntimeConfig, jitter: float) -> None:
    text = format_settings_poll_text(runtime.poll_interval, jitter)
    await message.answer(text, reply_markup=settings_poll_keyboard(runtime.poll_interval))


async def _send_alerts_menu(message: Message, runtime: BotRuntimeConfig) -> None:
    cfg = runtime.alerts
    await message.answer(
        format_alerts_menu_text(),
        reply_markup=alerts_menu_keyboard(
            cfg.v12.enabled,
            cfg.connect.enabled,
            cfg.soh.enabled,
            cfg.charging.enabled,
        ),
    )


def _charge_screen(cfg) -> tuple[str, Any]:
    trigger = cfg.normalized_trigger()
    max_pct = cfg.normalized_max()
    return (
        format_charge_alert_text(cfg.enabled, trigger, max_pct),
        charge_alert_keyboard(cfg.enabled, trigger, max_pct),
    )


def create_dispatcher(
    settings: Settings,
    storage: TelemetryStorage,
    runtime: BotRuntimeConfig,
) -> Dispatcher:
    dp = Dispatcher()
    jitter = settings.telegram_poll_jitter

    async def _guard(message: Message) -> bool:
        if _authorized(settings, message.from_user.id):
            return True
        await message.answer("Доступ запрещен.")
        return False

    async def _guard_callback(callback: CallbackQuery) -> bool:
        user = callback.from_user
        if user and _authorized(settings, user.id):
            return True
        await callback.answer("Доступ запрещен.", show_alert=True)
        return False

    @dp.message(Command("start", "help", "menu"))
    async def cmd_menu(message: Message) -> None:
        if not await _guard(message):
            return
        await _send_main_status(message, runtime, storage, jitter)

    @dp.message(F.text == BTN_MAIN)
    async def on_main_menu(message: Message) -> None:
        if not await _guard(message):
            return
        await _send_main_status(message, runtime, storage, jitter)

    @dp.callback_query(F.data == CB_NAV_MAIN)
    async def on_nav_main(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        await callback.answer()
        if callback.message:
            await _send_main_status(callback.message, runtime, storage, jitter)

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
        await _send_settings(message, runtime, jitter)

    @dp.callback_query(F.data.startswith(CB_POLL_PREFIX))
    async def on_poll_interval(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        seconds = parse_poll_callback_data(callback.data or "")
        if seconds is None or seconds not in POLL_INTERVAL_VALUES:
            await callback.answer("Неверный интервал.", show_alert=True)
            return
        runtime.set_poll_interval(seconds)
        runtime.save()
        label = format_poll_interval_label(seconds)
        await callback.answer(f"Интервал: {label}")
        if callback.message:
            text = format_settings_poll_text(seconds, jitter)
            await callback.message.edit_text(
                text,
                reply_markup=settings_poll_keyboard(seconds),
            )

    @dp.message(F.text == BTN_HISTORY)
    async def on_history(message: Message) -> None:
        if not await _guard(message):
            return
        count = storage.snapshot_count()
        await message.answer(
            format_history_menu_text(count),
            reply_markup=history_period_keyboard(),
        )

    @dp.callback_query(F.data.startswith(CB_HISTORY_PREFIX))
    async def on_history_export(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        try:
            days = parse_history_callback_data(callback.data or "")
        except (ValueError, TypeError):
            await callback.answer("Неверный период.", show_alert=True)
            return

        await callback.answer("Готовлю файл…")
        target = callback.message
        if not target:
            return

        try:
            count = await asyncio.to_thread(storage.snapshots_count_in_range, days=days)
            if count == 0:
                await target.answer(
                    f"Нет снимков {period_label(days)}.",
                    reply_markup=main_menu_keyboard(),
                )
                return
            await target.answer(
                f"Формирую Excel: {count} снимков, подождите…",
                reply_markup=main_menu_keyboard(),
            )
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
                export_path = Path(handle.name)
            try:
                await asyncio.to_thread(
                    export_history_xlsx_to_path,
                    storage,
                    export_path,
                    days=days,
                )
            except Exception:
                export_path.unlink(missing_ok=True)
                raise
        except Exception as exc:
            logger.exception("History export failed")
            await target.answer(f"Ошибка экспорта: {exc}", reply_markup=main_menu_keyboard())
            return

        filename = export_filename(days=days)
        try:
            await target.answer_document(
                FSInputFile(export_path, filename=filename),
                caption=f"История {period_label(days)} ({count} снимков)",
            )
        finally:
            export_path.unlink(missing_ok=True)

    @dp.message(F.text == BTN_ALERTS)
    async def on_alerts(message: Message) -> None:
        if not await _guard(message):
            return
        await _send_alerts_menu(message, runtime)

    @dp.callback_query(F.data == CB_ALERTS_BACK)
    async def on_alerts_back(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                format_alerts_menu_text(),
                reply_markup=alerts_menu_keyboard(
                    cfg.v12.enabled,
                    cfg.connect.enabled,
                    cfg.soh.enabled,
                    cfg.charging.enabled,
                ),
            )

    @dp.callback_query(F.data == CB_ALERTS_CHARGE)
    async def on_alerts_charge_open(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        runtime.awaiting_charge_max_input = False
        cfg = runtime.alerts.charging
        await callback.answer()
        if callback.message:
            text, keyboard = _charge_screen(cfg)
            await callback.message.edit_text(text, reply_markup=keyboard)

    @dp.callback_query(F.data == CB_ALERTS_V12)
    async def on_alerts_v12_open(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts.v12
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                format_v12_alert_text(cfg.enabled, cfg.normalized_threshold()),
                reply_markup=v12_alert_keyboard(cfg.enabled, cfg.normalized_threshold()),
            )

    @dp.callback_query(F.data == CB_ALERTS_CONNECT)
    async def on_alerts_connect_open(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts.connect
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                format_connect_alert_text(cfg.enabled),
                reply_markup=connect_alert_keyboard(cfg.enabled),
            )

    @dp.callback_query(F.data == CB_ALERTS_SOH)
    async def on_alerts_soh_open(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts.soh
        await callback.answer()
        if callback.message:
            await callback.message.edit_text(
                format_soh_alert_text(cfg.enabled),
                reply_markup=soh_alert_keyboard(cfg.enabled),
            )

    @dp.callback_query(F.data == CB_ALERTS_V12_TOGGLE)
    async def on_alerts_v12_toggle(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts.v12
        cfg.enabled = not cfg.enabled
        if not cfg.enabled:
            runtime.alerts.state.v12_low_active = False
        runtime.save()
        label = "включён" if cfg.enabled else "выключен"
        await callback.answer(f"12V: {label}")
        if callback.message:
            threshold = cfg.normalized_threshold()
            await callback.message.edit_text(
                format_v12_alert_text(cfg.enabled, threshold),
                reply_markup=v12_alert_keyboard(cfg.enabled, threshold),
            )

    @dp.callback_query(F.data == CB_ALERTS_CONNECT_TOGGLE)
    async def on_alerts_connect_toggle(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts.connect
        cfg.enabled = not cfg.enabled
        if not cfg.enabled:
            runtime.alerts.state.offline_active = False
        runtime.save()
        label = "включён" if cfg.enabled else "выключен"
        await callback.answer(f"Connect: {label}")
        if callback.message:
            await callback.message.edit_text(
                format_connect_alert_text(cfg.enabled),
                reply_markup=connect_alert_keyboard(cfg.enabled),
            )

    @dp.callback_query(F.data == CB_ALERTS_SOH_TOGGLE)
    async def on_alerts_soh_toggle(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts.soh
        cfg.enabled = not cfg.enabled
        if not cfg.enabled:
            runtime.alerts.state.last_soh_percent = None
        runtime.save()
        label = "включён" if cfg.enabled else "выключен"
        await callback.answer(f"SOH: {label}")
        if callback.message:
            await callback.message.edit_text(
                format_soh_alert_text(cfg.enabled),
                reply_markup=soh_alert_keyboard(cfg.enabled),
            )

    @dp.callback_query(F.data == CB_ALERTS_CHARGE_TOGGLE)
    async def on_alerts_charge_toggle(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        cfg = runtime.alerts.charging
        cfg.enabled = not cfg.enabled
        if not cfg.enabled:
            runtime.alerts.state.charging_sessions.clear()
        runtime.save()
        label = "включён" if cfg.enabled else "выключен"
        await callback.answer(f"Зарядка: {label}")
        if callback.message:
            text, keyboard = _charge_screen(cfg)
            await callback.message.edit_text(text, reply_markup=keyboard)

    @dp.callback_query(F.data.startswith("alerts:charge:thr:"))
    async def on_alerts_charge_trigger(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        trigger = parse_charge_trigger_callback(callback.data or "")
        if trigger is None:
            await callback.answer("Неверный триггер.", show_alert=True)
            return
        cfg = runtime.alerts.charging
        cfg.trigger_percent = trigger
        runtime.save()
        await callback.answer(f"Триггер: +{trigger}%")
        if callback.message:
            text, keyboard = _charge_screen(cfg)
            await callback.message.edit_text(text, reply_markup=keyboard)

    @dp.callback_query(F.data.startswith("alerts:charge:max:"))
    async def on_alerts_charge_max(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        data = callback.data or ""
        if data == CB_ALERTS_CHARGE_MAX_CUSTOM:
            runtime.awaiting_charge_max_input = True
            await callback.answer()
            if callback.message:
                await callback.message.answer(
                    "Введите целевой заряд от 0 до 100 (например, 95):",
                    reply_markup=main_menu_keyboard(),
                )
            return
        max_pct = parse_charge_max_callback(data)
        if max_pct is None:
            await callback.answer("Неверное значение.", show_alert=True)
            return
        runtime.awaiting_charge_max_input = False
        cfg = runtime.alerts.charging
        cfg.max_percent = max_pct
        runtime.save()
        await callback.answer(f"Цель: {max_pct}%")
        if callback.message:
            text, keyboard = _charge_screen(cfg)
            await callback.message.edit_text(text, reply_markup=keyboard)

    @dp.callback_query(F.data.startswith("alerts:v12:thr:"))
    async def on_alerts_v12_threshold(callback: CallbackQuery) -> None:
        if not await _guard_callback(callback):
            return
        threshold = parse_v12_threshold_callback(callback.data or "")
        if threshold is None:
            await callback.answer("Неверный порог.", show_alert=True)
            return
        cfg = runtime.alerts.v12
        cfg.threshold_v = threshold
        runtime.save()
        await callback.answer(f"Порог: {threshold:g} V")
        if callback.message:
            await callback.message.edit_text(
                format_v12_alert_text(cfg.enabled, threshold),
                reply_markup=v12_alert_keyboard(cfg.enabled, threshold),
            )

    @dp.message(F.text)
    async def fallback(message: Message) -> None:
        if not _authorized(settings, message.from_user.id):
            return
        if message.text in MENU_BUTTONS:
            return
        if runtime.awaiting_charge_max_input and message.text:
            max_pct = parse_charge_max_input(message.text)
            if max_pct is None:
                await message.answer(
                    "Нужно число от 0 до 100. Попробуйте снова или откройте «Контроль параметров».",
                    reply_markup=main_menu_keyboard(),
                )
                return
            runtime.awaiting_charge_max_input = False
            cfg = runtime.alerts.charging
            cfg.max_percent = max_pct
            runtime.save()
            text, keyboard = _charge_screen(cfg)
            await message.answer(
                f"Цель зарядки: {max_pct}%",
                reply_markup=main_menu_keyboard(),
            )
            await message.answer(text, reply_markup=keyboard)
            return
        await _send_main_status(message, runtime, storage, jitter)

    return dp


async def run_bot(settings: Settings) -> None:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    storage = TelemetryStorage(settings.voyah_db_path)
    runtime = BotRuntimeConfig(settings)
    bot = Bot(token=settings.telegram_bot_token)
    dp = create_dispatcher(settings, storage, runtime)

    async def periodic_collect() -> None:
        jitter = settings.telegram_poll_jitter
        logger.info(
            "Background telemetry collection ~every %.1f h (±%.0f%%)",
            runtime.poll_interval / 3600,
            jitter * 100,
        )
        while True:
            base = runtime.poll_interval
            delay = next_poll_delay_seconds(base, jitter)
            logger.info("Next background collect in %.0f min", delay / 60)
            await asyncio.sleep(delay)
            try:
                telemetries = await asyncio.to_thread(_fetch_and_save, settings, storage)
                await _dispatch_alert_notifications(bot, settings, runtime, telemetries)
            except SessionExpiredError:
                logger.exception("Periodic telemetry collection failed: session expired")
                try:
                    await _dispatch_session_revoked_alert(bot, settings, runtime)
                except Exception:
                    logger.exception("Failed to dispatch session-revoked alert")
            except Exception:
                logger.exception("Periodic telemetry collection failed")

    async def periodic_session_expiry_check() -> None:
        logger.info("Session expiry reminders: hourly check from 10:00 MSK (3/2/1 days)")
        while True:
            try:
                await _dispatch_session_expiry_reminders(bot, settings, runtime)
            except Exception:
                logger.exception("Session expiry reminder check failed")
            await asyncio.sleep(3600)

    logger.info("Starting Telegram bot...")
    asyncio.create_task(periodic_collect())
    asyncio.create_task(periodic_session_expiry_check())
    await dp.start_polling(bot)
