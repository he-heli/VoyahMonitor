from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from voyah_monitor.session import (
    load_session,
    refresh_token_from_session,
    token_expires_at,
    token_issued_at,
)
from voyah_monitor.timeutil import format_moscow, moscow_now, to_moscow

# Days remaining until JWT exp (late safety net).
DAYS_LEFT_REMINDERS = frozenset({7, 3, 2, 1})
# Full days since refresh-token iat (observed real life ~45 days).
AGE_DAY_REMINDERS = frozenset({40, 42, 44})
NOTIFY_HOUR_MSK = 10
# Stored in session_expiry_notified[exp_key] when server already rejected refresh.
REVOKED_MARKER = -1
# Age reminders stored as negative keys: -40, -42, -44.
AGE_NOTIFY_OFFSET = 0


@dataclass(frozen=True)
class SessionReminder:
    notify_key: int
    text: str
    log_label: str


def refresh_token_expires_at(session: dict[str, Any], base_url: str) -> datetime | None:
    token = refresh_token_from_session(session, base_url)
    if not token:
        return None
    return token_expires_at(token)


def refresh_token_issued_at(session: dict[str, Any], base_url: str) -> datetime | None:
    token = refresh_token_from_session(session, base_url)
    if not token:
        return None
    return token_issued_at(token)


def days_until_expiry(expires_at: datetime, *, now: datetime | None = None) -> int:
    current = _as_utc(now if now is not None else datetime.now(UTC))
    expires_at = _as_utc(expires_at)
    seconds = (expires_at - current).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 86400)


def days_since_issued(issued_at: datetime, *, now: datetime | None = None) -> int:
    current = _as_utc(now if now is not None else datetime.now(UTC))
    issued_at = _as_utc(issued_at)
    seconds = (current - issued_at).total_seconds()
    if seconds < 0:
        return 0
    return int(seconds // 86400)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def age_notify_key(age_days: int) -> int:
    return -(age_days + AGE_NOTIFY_OFFSET)


def pick_session_reminder(
    *,
    expires_at: datetime,
    issued_at: datetime | None,
    notified_for_exp: list[int],
    now: datetime | None = None,
) -> SessionReminder | None:
    """Choose at most one due reminder (age first, then days-left)."""
    local_now = to_moscow(now) if now is not None else moscow_now()
    if local_now.hour < NOTIFY_HOUR_MSK:
        return None

    if issued_at is not None:
        age_days = days_since_issued(issued_at, now=local_now)
        if age_days in AGE_DAY_REMINDERS:
            key = age_notify_key(age_days)
            if key not in notified_for_exp:
                return SessionReminder(
                    notify_key=key,
                    text=format_session_age_message(age_days, expires_at),
                    log_label=f"age={age_days}d",
                )

    days_left = days_until_expiry(expires_at, now=local_now)
    if days_left in DAYS_LEFT_REMINDERS and days_left not in notified_for_exp:
        return SessionReminder(
            notify_key=days_left,
            text=format_session_expiry_message(days_left, expires_at),
            log_label=f"days_left={days_left}",
        )
    return None


def should_notify_session_expiry(
    *,
    expires_at: datetime,
    notified_for_exp: list[int],
    issued_at: datetime | None = None,
    now: datetime | None = None,
) -> int | None:
    """Compatibility helper: returns notify_key or None."""
    reminder = pick_session_reminder(
        expires_at=expires_at,
        issued_at=issued_at,
        notified_for_exp=notified_for_exp,
        now=now,
    )
    return reminder.notify_key if reminder else None


def format_session_expiry_message(days_left: int, expires_at: datetime) -> str:
    when = format_moscow(expires_at, fmt="%d.%m.%Y %H:%M")
    if days_left == 1:
        lead = "через 1 день"
    else:
        lead = f"через {days_left} дн."
    return (
        f"⚠️ Сессия VOYAH по JWT истекает {lead} ({when} МСК).\n"
        f"Нужен повторный login на ПК и обновление session.json на VPS:\n"
        f"./scripts/local-login.sh → scp data/session.json → restart бота."
    )


def format_session_age_message(age_days: int, expires_at: datetime) -> str:
    when = format_moscow(expires_at, fmt="%d.%m.%Y %H:%M")
    return (
        f"⚠️ Сессии VOYAH уже {age_days} дн. "
        f"(на практике refresh часто отзывают около 45-го дня).\n"
        f"JWT ещё показывает срок до {when} МСК — лучше обновить login заранее.\n"
        f"./scripts/local-login.sh → scp data/session.json → restart бота."
    )


def format_session_revoked_message(*, expires_at: datetime | None) -> str:
    lines = [
        "🚫 Сессия VOYAH недействительна.",
        "Сервер отклонил refresh token (истёк или отозван).",
    ]
    if expires_at is not None:
        when = format_moscow(expires_at, fmt="%d.%m.%Y %H:%M")
        lines.append(
            f"В JWT ещё указан срок до {when} МСК — на него нельзя полагаться."
        )
    lines.extend(
        [
            "Нужен повторный login на ПК и обновление session.json на VPS:",
            "./scripts/local-login.sh → scp data/session.json → restart бота.",
        ]
    )
    return "\n".join(lines)


def should_notify_session_revoked(notified_for_exp: list[int]) -> bool:
    return REVOKED_MARKER not in notified_for_exp


def load_refresh_expires_at(session_path, base_url: str) -> datetime | None:
    try:
        session = load_session(session_path)
    except (OSError, FileNotFoundError, ValueError):
        return None
    return refresh_token_expires_at(session, base_url)


def load_refresh_issued_at(session_path, base_url: str) -> datetime | None:
    try:
        session = load_session(session_path)
    except (OSError, FileNotFoundError, ValueError):
        return None
    return refresh_token_issued_at(session, base_url)


def exp_key(expires_at: datetime) -> str:
    return str(int(expires_at.astimezone(UTC).timestamp()))
