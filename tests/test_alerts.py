from __future__ import annotations

from voyah_monitor.alert_settings import (
    AlertConfig,
    AlertState,
    ConnectAlertConfig,
    SohAlertConfig,
    V12AlertConfig,
)
from voyah_monitor.alerts import evaluate_alerts
from voyah_monitor.telemetry import VehicleTelemetry


def _telemetry(
    *,
    v12: float | None = None,
    online: bool | None = None,
    soh: float | None = None,
) -> VehicleTelemetry:
    return VehicleTelemetry(
        name="ФРИ / FREE",
        v12_voltage=v12,
        is_online=online,
        soh_percent=soh,
    )


def test_v12_alert_fires_below_threshold() -> None:
    config = AlertConfig(
        v12=V12AlertConfig(enabled=True, threshold_v=12.5),
        state=AlertState(),
    )
    messages, state = evaluate_alerts(_telemetry(v12=12.2), config)
    assert len(messages) == 1
    assert messages[0].kind == "v12_low"
    assert state.v12_low_active is True


def test_v12_recovery_message() -> None:
    config = AlertConfig(
        v12=V12AlertConfig(enabled=True, threshold_v=12.5),
        state=AlertState(v12_low_active=True),
    )
    messages, state = evaluate_alerts(_telemetry(v12=12.9), config)
    assert len(messages) == 1
    assert messages[0].kind == "v12_ok"
    assert state.v12_low_active is False


def test_connect_offline_and_online() -> None:
    config = AlertConfig(
        connect=ConnectAlertConfig(enabled=True),
        state=AlertState(),
    )
    offline_msgs, state = evaluate_alerts(_telemetry(online=False), config)
    assert offline_msgs[0].kind == "offline"
    assert state.offline_active is True

    config.state = state
    online_msgs, state = evaluate_alerts(_telemetry(online=True), config)
    assert online_msgs[0].kind == "online"
    assert state.offline_active is False


def test_disabled_alerts_produce_no_messages() -> None:
    config = AlertConfig()
    messages, _ = evaluate_alerts(_telemetry(v12=11.0, online=False), config)
    assert messages == []


def test_soh_first_reading_sets_baseline_without_alert() -> None:
    config = AlertConfig(soh=SohAlertConfig(enabled=True), state=AlertState())
    messages, state = evaluate_alerts(_telemetry(soh=100), config)
    assert messages == []
    assert state.last_soh_percent == 100.0


def test_soh_change_triggers_alert() -> None:
    config = AlertConfig(
        soh=SohAlertConfig(enabled=True),
        state=AlertState(last_soh_percent=100.0),
    )
    messages, state = evaluate_alerts(_telemetry(soh=99), config)
    assert len(messages) == 1
    assert messages[0].kind == "soh_change"
    assert "100" in messages[0].text
    assert "99" in messages[0].text
    assert state.last_soh_percent == 99.0
