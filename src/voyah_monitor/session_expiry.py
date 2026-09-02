from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from voyah_monitor.session import load_session, refresh_token_from_session, token_expires_at
from voyah_monitor.timeutil import format_moscow, moscow_now, to_moscow

REMINDER_DAYS = frozenset({1, 2, 3})
NOTIFY_HOUR_MSK = 10
# Stored in session_expiry_notified[exp_key] when server already rejected refresh.
REVOKED_MARKER = -1


def refresh_token_expires_at(session: dict[str, Any], base_url: str) -> datetime | None:
    token = refresh_token_from_session(session, base_url)
    if not token:
        return None
    return token_expires_at(token)


def days_until_expiry(expires_at: datetime, *, now: datetime | None = None) -> int:
    current = now if now is not None else datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    else:
        expires_at = expires_at.astimezone(UTC)
    seconds = (expires_at - current).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 86400)


def should_notify_session_expiry(
    *,
    expires_at: datetime,
    notified_for_exp: list[int],
    now: datetime | None = None,
) -> int | None:
    """Return days_left if a reminder should be sent now, else None."""
    local_now = to_moscow(now) if now is not None else moscow_now()
    if local_now.hour < NOTIFY_HOUR_MSK:
        return None

    days_left = days_until_expiry(expires_at, now=local_now)
    if days_left not in REMINDER_DAYS:
        return None
    if days_left in notified_for_exp:
        return None
    return days_left


def format_session_expiry_message(days_left: int, expires_at: datetime) -> str:
    when = format_moscow(expires_at, fmt="%d.%m.%Y %H:%M")
    if days_left == 1:
        lead = "через 1 день"
    else:
        lead = f"через {days_left} дн."
    return (
        f"⚠️ Сессия VOYAH истекает {lead} ({when} МСК).\n"
        f"Нужен повторный login на ПК и обновление session.json на VPS:\n"
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


def exp_key(expires_at: datetime) -> str:
    return str(int(expires_at.astimezone(UTC).timestamp()))
