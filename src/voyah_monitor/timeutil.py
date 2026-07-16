from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def to_moscow(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(MSK)


def moscow_now() -> datetime:
    return datetime.now(MSK)


def moscow_date(value: datetime | None = None) -> date:
    if value is None:
        return moscow_now().date()
    return to_moscow(value).date()


def format_moscow(
    value: datetime,
    *,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    return to_moscow(value).strftime(fmt)
