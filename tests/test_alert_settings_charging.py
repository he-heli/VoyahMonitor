from __future__ import annotations

from pathlib import Path

from voyah_monitor.alert_settings import (
    BotSettingsStore,
    ChargingSessionState,
    DEFAULT_CHARGE_MAX,
    DEFAULT_CHARGE_TRIGGER,
)


def test_bot_settings_store_persists_charging_config(tmp_path: Path) -> None:
    path = tmp_path / "bot_settings.json"
    store = BotSettingsStore(path, default_poll_interval=3600)
    store.alerts.charging.enabled = True
    store.alerts.charging.trigger_percent = 10
    store.alerts.charging.max_percent = 90
    store.alerts.state.charging_sessions["car1"] = ChargingSessionState(
        active=True,
        last_notified_percent=50.0,
        points=[("2026-06-16T10:00:00+00:00", 50.0)],
    )
    store.save()

    reloaded = BotSettingsStore(path, default_poll_interval=3600)
    assert reloaded.alerts.charging.enabled is True
    assert reloaded.alerts.charging.trigger_percent == 10
    assert reloaded.alerts.charging.max_percent == 90
    session = reloaded.alerts.state.charging_sessions["car1"]
    assert session.active is True
    assert session.last_notified_percent == 50.0
    assert session.points == [("2026-06-16T10:00:00+00:00", 50.0)]


def test_charging_defaults() -> None:
    path = Path("/nonexistent/bot_settings.json")
    store = BotSettingsStore(path, default_poll_interval=3600)
    assert store.alerts.charging.max_percent == DEFAULT_CHARGE_MAX
    assert store.alerts.charging.trigger_percent == DEFAULT_CHARGE_TRIGGER
    assert DEFAULT_CHARGE_MAX == 95
