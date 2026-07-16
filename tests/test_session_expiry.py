from __future__ import annotations

from datetime import UTC, datetime

from voyah_monitor.session_expiry import (
    days_until_expiry,
    format_session_expiry_message,
    should_notify_session_expiry,
)


def test_days_until_expiry_floors_to_full_days() -> None:
    now = datetime(2026, 10, 11, 7, 0, tzinfo=UTC)  # 10:00 MSK
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)
    assert days_until_expiry(expires, now=now) == 3


def test_should_notify_only_after_10_msk_for_3_2_1() -> None:
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)

    before_ten = datetime(2026, 10, 11, 6, 30, tzinfo=UTC)  # 09:30 MSK
    assert (
        should_notify_session_expiry(
            expires_at=expires,
            notified_for_exp=[],
            now=before_ten,
        )
        is None
    )

    at_ten = datetime(2026, 10, 11, 7, 15, tzinfo=UTC)  # 10:15 MSK
    assert (
        should_notify_session_expiry(
            expires_at=expires,
            notified_for_exp=[],
            now=at_ten,
        )
        == 3
    )

    assert (
        should_notify_session_expiry(
            expires_at=expires,
            notified_for_exp=[3],
            now=at_ten,
        )
        is None
    )


def test_format_session_expiry_message_uses_moscow() -> None:
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)
    text = format_session_expiry_message(3, expires)
    assert "через 3 дн." in text
    assert "14.10.2026 23:39 МСК" in text
    assert "local-login" in text


def test_days_left_one_and_two() -> None:
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)
    day2 = datetime(2026, 10, 12, 7, 0, tzinfo=UTC)
    day1 = datetime(2026, 10, 13, 7, 0, tzinfo=UTC)
    assert days_until_expiry(expires, now=day2) == 2
    assert days_until_expiry(expires, now=day1) == 1
    assert (
        should_notify_session_expiry(
            expires_at=expires,
            notified_for_exp=[3],
            now=day2,
        )
        == 2
    )
