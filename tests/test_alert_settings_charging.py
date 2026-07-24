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
        points=[("2026-06-16T10:00:00+00:00", 50.0, 21.5)],
    )
    store.save()

    reloaded = BotSettingsStore(path, default_poll_interval=3600)
    assert reloaded.alerts.charging.enabled is True
    assert reloaded.alerts.charging.trigger_percent == 10
    assert reloaded.alerts.charging.max_percent == 90
    session = reloaded.alerts.state.charging_sessions["car1"]
    assert session.active is True
    assert session.last_notified_percent == 50.0
    assert session.points == [("2026-06-16T10:00:00+00:00", 50.0, 21.5)]


def test_bot_settings_loads_legacy_two_field_points(tmp_path: Path) -> None:
    path = tmp_path / "bot_settings.json"
    path.write_text(
        '{"poll_interval_seconds":3600,"alerts":{"v12":{"enabled":false,"threshold_v":12.5},'
        '"connect":{"enabled":false},"soh":{"enabled":false},'
        '"charging":{"enabled":true,"trigger_percent":5,"max_percent":95}},'
        '"alert_state":{"v12_low_active":false,"offline_active":false,"last_soh_percent":null,'
        '"charging_sessions":{"car1":{"active":true,"last_notified_percent":50.0,'
        '"last_seen_percent":null,"points":[["2026-06-16T10:00:00+00:00",50.0]]}}}}\n',
        encoding="utf-8",
    )
    store = BotSettingsStore(path, default_poll_interval=3600)
    assert store.alerts.state.charging_sessions["car1"].points == [
        ("2026-06-16T10:00:00+00:00", 50.0, None)
    ]


def test_charging_defaults() -> None:
    path = Path("/nonexistent/bot_settings.json")
    store = BotSettingsStore(path, default_poll_interval=3600)
    assert store.alerts.charging.max_percent == DEFAULT_CHARGE_MAX
    assert store.alerts.charging.trigger_percent == DEFAULT_CHARGE_TRIGGER
    assert DEFAULT_CHARGE_MAX == 95
