from __future__ import annotations

from datetime import UTC, datetime

from voyah_monitor.session_expiry import (
    REVOKED_MARKER,
    age_notify_key,
    days_since_issued,
    days_until_expiry,
    format_session_age_message,
    format_session_expiry_message,
    format_session_revoked_message,
    pick_session_reminder,
    should_notify_session_expiry,
    should_notify_session_revoked,
)


def test_days_until_expiry_floors_to_full_days() -> None:
    now = datetime(2026, 10, 11, 7, 0, tzinfo=UTC)  # 10:00 MSK
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)
    assert days_until_expiry(expires, now=now) == 3


def test_age_reminders_at_40_42_44() -> None:
    issued = datetime(2026, 7, 16, 20, 39, 48, tzinfo=UTC)
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)
    # age 40 starts at 2026-08-25 20:39:48 UTC → next 10:15 MSK is Aug 26 07:15 UTC
    day40 = datetime(2026, 8, 26, 7, 15, tzinfo=UTC)
    assert days_since_issued(issued, now=day40) == 40

    reminder = pick_session_reminder(
        expires_at=expires,
        issued_at=issued,
        notified_for_exp=[],
        now=day40,
    )
    assert reminder is not None
    assert reminder.notify_key == age_notify_key(40)
    assert "40 дн." in reminder.text
    assert "45-го" in reminder.text

    assert (
        pick_session_reminder(
            expires_at=expires,
            issued_at=issued,
            notified_for_exp=[age_notify_key(40)],
            now=day40,
        )
        is None
    )

    day42 = datetime(2026, 8, 28, 7, 15, tzinfo=UTC)
    reminder42 = pick_session_reminder(
        expires_at=expires,
        issued_at=issued,
        notified_for_exp=[age_notify_key(40)],
        now=day42,
    )
    assert reminder42 is not None
    assert reminder42.notify_key == age_notify_key(42)


def test_jwt_days_left_reminders_7_3_2_1() -> None:
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)
    issued = datetime(2026, 7, 16, 20, 39, 48, tzinfo=UTC)

    before_ten = datetime(2026, 10, 7, 6, 30, tzinfo=UTC)  # 09:30 MSK, 7d left
    assert (
        pick_session_reminder(
            expires_at=expires,
            issued_at=issued,
            notified_for_exp=[],
            now=before_ten,
        )
        is None
    )

    at_ten = datetime(2026, 10, 7, 7, 15, tzinfo=UTC)  # 10:15 MSK
    reminder = pick_session_reminder(
        expires_at=expires,
        issued_at=issued,
        notified_for_exp=[],
        now=at_ten,
    )
    assert reminder is not None
    assert reminder.notify_key == 7
    assert "через 7 дн." in reminder.text

    assert should_notify_session_expiry(
        expires_at=expires,
        issued_at=issued,
        notified_for_exp=[7],
        now=at_ten,
    ) is None


def test_age_reminder_preferred_over_days_left_same_day() -> None:
    from datetime import timedelta

    issued = datetime(2026, 7, 16, 20, 39, 48, tzinfo=UTC)
    expires = issued + timedelta(days=47)
    # first 10:15 MSK on/after age==40
    now = datetime(2026, 8, 26, 7, 15, tzinfo=UTC)
    assert days_since_issued(issued, now=now) == 40
    assert days_until_expiry(expires, now=now) == 6  # not in set; still prefer age path

    # Make days_left also 7 on an age-40 morning:
    expires = now + timedelta(days=7, hours=5)
    assert days_until_expiry(expires, now=now) == 7
    reminder = pick_session_reminder(
        expires_at=expires,
        issued_at=issued,
        notified_for_exp=[],
        now=now,
    )
    assert reminder is not None
    assert reminder.notify_key == age_notify_key(40)


def test_format_messages() -> None:
    expires = datetime(2026, 10, 14, 20, 39, 48, tzinfo=UTC)
    assert "14.10.2026 23:39 МСК" in format_session_expiry_message(3, expires)
    assert "local-login" in format_session_age_message(42, expires)
    text = format_session_revoked_message(expires_at=expires)
    assert "недействительна" in text


def test_session_revoked_notify_once() -> None:
    assert should_notify_session_revoked([]) is True
    assert should_notify_session_revoked([3, 2]) is True
    assert should_notify_session_revoked([REVOKED_MARKER]) is False
