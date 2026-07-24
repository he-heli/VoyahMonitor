from __future__ import annotations

from datetime import UTC, datetime, timedelta

from voyah_monitor.alert_settings import (
    AlertConfig,
    AlertState,
    ChargingAlertConfig,
    ChargingSessionState,
)
from voyah_monitor.alerts import evaluate_alerts
from voyah_monitor.charging_chart import render_charging_chart
from voyah_monitor.telemetry import VehicleTelemetry


def _telemetry(
    *,
    battery: float | None = None,
    charging: bool | None = None,
    battery_temp_c: float | None = None,
    captured_at: datetime | None = None,
    vehicle_id: str = "car1",
) -> VehicleTelemetry:
    return VehicleTelemetry(
        vehicle_id=vehicle_id,
        name="ФРИ / FREE",
        battery_percent=battery,
        is_charging=charging,
        battery_temp_c=battery_temp_c,
        captured_at=captured_at or datetime(2026, 6, 16, 10, 0, tzinfo=UTC),
    )


def _charging_config(**kwargs) -> AlertConfig:
    return AlertConfig(
        charging=ChargingAlertConfig(enabled=True, **kwargs),
        state=AlertState(),
    )


def test_charging_first_reading_starts_session_without_alert() -> None:
    config = _charging_config(trigger_percent=5, max_percent=95)
    messages, state = evaluate_alerts(_telemetry(battery=40, charging=True), config)
    assert messages == []
    session = state.charging_sessions["car1"]
    assert session.active is True
    assert session.last_notified_percent == 40.0
    assert len(session.points) == 1


def test_charging_triggers_on_trigger_increase() -> None:
    config = _charging_config(trigger_percent=5, max_percent=95)
    config.state.charging_sessions["car1"] = ChargingSessionState(
        active=True,
        last_notified_percent=40.0,
        last_seen_percent=40.0,
        points=[
            ("2026-06-16T10:00:00+00:00", 40.0, 22.0),
            ("2026-06-16T10:30:00+00:00", 42.0, 24.0),
        ],
    )
    messages, state = evaluate_alerts(
        _telemetry(
            battery=45,
            charging=True,
            battery_temp_c=26.5,
            captured_at=datetime(2026, 6, 16, 11, 0, tzinfo=UTC),
        ),
        config,
    )
    assert len(messages) == 1
    assert messages[0].kind == "charge_progress"
    assert "45%" in messages[0].text
    assert "Темп. АКБ: 26.5 °C" in messages[0].text
    assert "Скорость:" in messages[0].text
    assert "До 95%" in messages[0].text
    assert "Окончание (~МСК):" in messages[0].text
    assert messages[0].photo_png is not None
    assert len(messages[0].photo_png) > 1000
    assert state.charging_sessions["car1"].last_notified_percent == 45.0
    assert state.charging_sessions["car1"].points[-1][2] == 26.5


def test_charging_no_alert_below_trigger() -> None:
    config = _charging_config(trigger_percent=5, max_percent=95)
    config.state.charging_sessions["car1"] = ChargingSessionState(
        active=True,
        last_notified_percent=40.0,
        last_seen_percent=40.0,
        points=[("2026-06-16T10:00:00+00:00", 40.0, None)],
    )
    messages, _ = evaluate_alerts(_telemetry(battery=43, charging=True), config)
    assert messages == []


def test_charging_completes_at_max_percent() -> None:
    config = _charging_config(trigger_percent=5, max_percent=95)
    config.state.charging_sessions["car1"] = ChargingSessionState(
        active=True,
        last_notified_percent=90.0,
        last_seen_percent=90.0,
        points=[
            ("2026-06-16T10:00:00+00:00", 80.0, 20.0),
            ("2026-06-16T11:00:00+00:00", 90.0, 28.0),
        ],
    )
    messages, state = evaluate_alerts(
        _telemetry(battery=95, charging=True, battery_temp_c=30.0),
        config,
    )
    assert len(messages) == 1
    assert messages[0].kind == "charge_complete"
    assert "95%" in messages[0].text
    assert "Темп. АКБ: 30 °C" in messages[0].text
    assert "car1" not in state.charging_sessions


def test_charging_resets_when_stopped() -> None:
    config = _charging_config()
    config.state.charging_sessions["car1"] = ChargingSessionState(
        active=True,
        last_notified_percent=50.0,
        last_seen_percent=55.0,
        points=[("2026-06-16T10:00:00+00:00", 50.0, None)],
    )
    messages, state = evaluate_alerts(_telemetry(battery=54, charging=False), config)
    assert messages == []
    assert "car1" not in state.charging_sessions


def test_charging_disabled_clears_sessions() -> None:
    config = AlertConfig(
        charging=ChargingAlertConfig(enabled=False),
        state=AlertState(
            charging_sessions={
                "car1": ChargingSessionState(active=True, last_notified_percent=50.0),
            }
        ),
    )
    messages, state = evaluate_alerts(_telemetry(battery=60, charging=True), config)
    assert messages == []
    assert state.charging_sessions == {}


def test_charging_detected_by_soc_increase() -> None:
    config = _charging_config()
    messages, state = evaluate_alerts(
        _telemetry(battery=41, charging=None, captured_at=datetime(2026, 6, 16, 10, 0, tzinfo=UTC)),
        config,
    )
    assert messages == []
    assert state.charging_sessions["car1"].active is False

    config.state = state
    messages, state = evaluate_alerts(
        _telemetry(battery=42, charging=None, captured_at=datetime(2026, 6, 16, 10, 30, tzinfo=UTC)),
        config,
    )
    assert messages == []
    assert state.charging_sessions["car1"].active is True


def test_render_charging_chart_returns_png() -> None:
    start = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)
    points = [
        (start, 40.0, 18.0),
        (start + timedelta(minutes=30), 45.0, 22.0),
    ]
    png = render_charging_chart(
        points,
        max_percent=95,
        forecast_end=start + timedelta(hours=2),
        current_soc=45.0,
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_charging_chart_without_temp_still_works() -> None:
    start = datetime(2026, 6, 16, 10, 0, tzinfo=UTC)
    png = render_charging_chart(
        [(start, 40.0), (start + timedelta(minutes=30), 45.0)],
        max_percent=95,
        forecast_end=None,
        current_soc=45.0,
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
