from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from voyah_monitor.alert_settings import AlertConfig, V12_THRESHOLD_OPTIONS

# --- Main menu (reply keyboard) ---

BTN_FULL = "Полная информация"
BTN_BRIEF = "Краткая информация"
BTN_SETTINGS = "Настройки"
BTN_ALERTS = "Контроль параметров"
BTN_LOCATION = "Найти машину"
BTN_SNAPSHOT = "Снимок в базу"
BTN_HISTORY = "Скачать историю"
BTN_MAIN = "🏠 Главное меню"

MENU_BUTTONS = frozenset(
    {
        BTN_FULL,
        BTN_BRIEF,
        BTN_SETTINGS,
        BTN_ALERTS,
        BTN_LOCATION,
        BTN_SNAPSHOT,
        BTN_HISTORY,
        BTN_MAIN,
    }
)

CB_NAV_MAIN = "nav:main"

# History export periods (days); None = all time
HISTORY_PERIOD_OPTIONS: tuple[tuple[int | None, str], ...] = (
    (7, "7 дней"),
    (30, "30 дней"),
    (90, "90 дней"),
    (None, "За всё время"),
)

CB_HISTORY_PREFIX = "history:"

# --- Settings: background poll interval ---

POLL_INTERVAL_OPTIONS: tuple[tuple[int, str], ...] = (
    (300, "5 минут"),
    (1800, "30 минут"),
    (3600, "1 час"),
    (14400, "4 часа"),
    (43200, "12 часов"),
    (86400, "24 часа"),
)

POLL_INTERVAL_VALUES = frozenset(seconds for seconds, _ in POLL_INTERVAL_OPTIONS)

CB_POLL_PREFIX = "poll:"


def format_poll_interval_label(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours} ч"
    if seconds % 60 == 0:
        return f"{seconds // 60} мин"
    return f"{seconds} с"


def format_settings_poll_text(interval_seconds: int, jitter_fraction: float) -> str:
    jitter_pct = int(jitter_fraction * 100)
    label = format_poll_interval_label(interval_seconds)
    spread_low = format_poll_interval_label(
        max(60, int(interval_seconds * (1 - jitter_fraction))),
    )
    spread_high = format_poll_interval_label(int(interval_seconds * (1 + jitter_fraction)))
    return (
        "⚙️ Настройки\n\n"
        "Фоновый сбор снимков в SQLite (кнопка «Снимок в базу» не нужна — идёт автоматически):\n"
        f"• Интервал: {label} (±{jitter_pct}%)\n"
        f"• Фактически: примерно {spread_low}–{spread_high}\n\n"
        "Выберите интервал:"
    )


def settings_poll_keyboard(current_interval: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for seconds, label in POLL_INTERVAL_OPTIONS:
        mark = " ✓" if seconds == current_interval else ""
        row.append(
            InlineKeyboardButton(
                text=f"{label}{mark}",
                callback_data=f"{CB_POLL_PREFIX}{seconds}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_poll_callback_data(data: str) -> int | None:
    if not data.startswith(CB_POLL_PREFIX):
        return None
    try:
        return int(data[len(CB_POLL_PREFIX) :])
    except ValueError:
        return None

PLACEHOLDER_ALERTS = ""  # unused; kept for backwards compatibility in imports

# --- Alerts: 12V + Connect ---

CB_ALERTS_PREFIX = "alerts:"
CB_ALERTS_V12 = "alerts:v12"
CB_ALERTS_CONNECT = "alerts:connect"
CB_ALERTS_SOH = "alerts:soh"
CB_ALERTS_V12_TOGGLE = "alerts:v12:toggle"
CB_ALERTS_CONNECT_TOGGLE = "alerts:connect:toggle"
CB_ALERTS_SOH_TOGGLE = "alerts:soh:toggle"
CB_ALERTS_V12_THR_PREFIX = "alerts:v12:thr:"
CB_ALERTS_BACK = "alerts:back"


def _status_emoji(enabled: bool) -> str:
    return "🟢" if enabled else "🔴"


def format_alerts_menu_text() -> str:
    return (
        "🔔 Контроль параметров\n\n"
        "🟢 — контроль включён, 🔴 — выключен.\n"
        "Выберите параметр:"
    )


def alerts_menu_keyboard(
    v12_enabled: bool,
    connect_enabled: bool,
    soh_enabled: bool,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(v12_enabled)} 12V",
                    callback_data=CB_ALERTS_V12,
                ),
                InlineKeyboardButton(
                    text=f"{_status_emoji(connect_enabled)} Connect",
                    callback_data=CB_ALERTS_CONNECT,
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"{_status_emoji(soh_enabled)} SOH",
                    callback_data=CB_ALERTS_SOH,
                ),
            ],
        ]
    )


def format_v12_alert_text(enabled: bool, threshold_v: float) -> str:
    status = "включён" if enabled else "выключен"
    return (
        "🔋 Батарея 12V\n\n"
        f"Контроль: {status}\n"
        f"Порог: {threshold_v:g} V — уведомление, если напряжение ниже порога.\n\n"
        "Выберите порог или включите/выключите контроль:"
    )


def _format_threshold_label(value: float) -> str:
    if value == int(value):
        return f"{int(value)}V"
    return f"{value:g}V".replace(".", ",")


def v12_alert_keyboard(enabled: bool, threshold_v: float) -> InlineKeyboardMarkup:
    toggle_text = "Выключить контроль" if enabled else "Включить контроль"
    threshold_row: list[InlineKeyboardButton] = []
    for value in V12_THRESHOLD_OPTIONS:
        mark = " ✓" if value == threshold_v else ""
        threshold_row.append(
            InlineKeyboardButton(
                text=f"{_format_threshold_label(value)}{mark}",
                callback_data=f"{CB_ALERTS_V12_THR_PREFIX}{value}",
            )
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=CB_ALERTS_V12_TOGGLE)],
            threshold_row[:2],
            threshold_row[2:],
            _nav_back_row(back_callback=CB_ALERTS_BACK),
        ]
    )


def _nav_back_row(*, back_callback: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text="« Назад", callback_data=back_callback)]


def format_connect_alert_text(enabled: bool) -> str:
    status = "включён" if enabled else "выключен"
    return (
        "📡 Connect (на связи)\n\n"
        f"Контроль: {status}\n"
        "Уведомление, если автомобиль не на связи, и когда связь восстановится."
    )


def connect_alert_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "Выключить контроль" if enabled else "Включить контроль"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=CB_ALERTS_CONNECT_TOGGLE)],
            _nav_back_row(back_callback=CB_ALERTS_BACK),
        ]
    )


def format_soh_alert_text(enabled: bool) -> str:
    status = "включён" if enabled else "выключен"
    return (
        "🔋 SOH (состояние батареи)\n\n"
        f"Контроль: {status}\n"
        "Уведомление при любом изменении SOH, %.\n"
        "Первое значение после включения запоминается без алерта."
    )


def soh_alert_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    toggle_text = "Выключить контроль" if enabled else "Включить контроль"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=CB_ALERTS_SOH_TOGGLE)],
            _nav_back_row(back_callback=CB_ALERTS_BACK),
        ]
    )


def parse_v12_threshold_callback(data: str) -> float | None:
    if not data.startswith(CB_ALERTS_V12_THR_PREFIX):
        return None
    try:
        value = float(data[len(CB_ALERTS_V12_THR_PREFIX) :])
    except ValueError:
        return None
    if value in V12_THRESHOLD_OPTIONS:
        return value
    return None



def format_bot_status_text(
    *,
    snapshot_count: int,
    poll_interval_seconds: int,
    jitter_fraction: float,
    alerts: AlertConfig,
) -> str:
    jitter_pct = int(jitter_fraction * 100)
    poll_label = format_poll_interval_label(poll_interval_seconds)
    spread_low = format_poll_interval_label(
        max(60, int(poll_interval_seconds * (1 - jitter_fraction))),
    )
    spread_high = format_poll_interval_label(int(poll_interval_seconds * (1 + jitter_fraction)))

    def _ctrl(name: str, enabled: bool, extra: str = "") -> str:
        mark = "🟢 вкл" if enabled else "🔴 выкл"
        suffix = f" ({extra})" if extra and enabled else ""
        return f"• {name}: {mark}{suffix}"

    v12_extra = ""
    if alerts.v12.enabled:
        v12_extra = f"порог {alerts.v12.normalized_threshold():g} V"

    lines = [
        "VOYAH Monitor",
        "",
        f"Снимков в базе: {snapshot_count}",
        f"Опрос сайта (фон): ~{poll_label} (±{jitter_pct}%), обычно {spread_low}–{spread_high}",
        "",
        "Контроль параметров:",
        _ctrl("12V", alerts.v12.enabled, v12_extra),
        _ctrl("Connect", alerts.connect.enabled),
        _ctrl("SOH", alerts.soh.enabled),
        "",
        "Выберите действие кнопками ниже.",
    ]
    return "\n".join(lines)


def format_history_menu_text(snapshot_count: int) -> str:
    return (
        "📥 Скачать историю\n\n"
        f"В базе {snapshot_count} снимков.\n"
        "Выберите период — пришлю файл Excel (.xlsx) с накопленными данными."
    )


def history_period_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for days, label in HISTORY_PERIOD_OPTIONS:
        suffix = "all" if days is None else str(days)
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"{CB_HISTORY_PREFIX}{suffix}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_history_callback_data(data: str) -> int | None:
    if not data.startswith(CB_HISTORY_PREFIX):
        raise ValueError("invalid history callback")
    token = data[len(CB_HISTORY_PREFIX) :]
    if token == "all":
        return None
    days = int(token)
    valid = {d for d, _ in HISTORY_PERIOD_OPTIONS if d is not None}
    if days not in valid:
        raise ValueError("unsupported history period")
    return days


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_FULL), KeyboardButton(text=BTN_BRIEF)],
            [KeyboardButton(text=BTN_LOCATION), KeyboardButton(text=BTN_SNAPSHOT)],
            [KeyboardButton(text=BTN_HISTORY)],
            [KeyboardButton(text=BTN_SETTINGS), KeyboardButton(text=BTN_ALERTS)],
            [KeyboardButton(text=BTN_MAIN)],
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
