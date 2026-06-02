from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

V12_THRESHOLD_OPTIONS: tuple[float, ...] = (13.0, 12.8, 12.5, 12.0)
DEFAULT_V12_THRESHOLD = 12.5


@dataclass
class V12AlertConfig:
    enabled: bool = False
    threshold_v: float = DEFAULT_V12_THRESHOLD

    def normalized_threshold(self) -> float:
        if self.threshold_v in V12_THRESHOLD_OPTIONS:
            return self.threshold_v
        return DEFAULT_V12_THRESHOLD


@dataclass
class ConnectAlertConfig:
    enabled: bool = False


@dataclass
class SohAlertConfig:
    enabled: bool = False


@dataclass
class AlertState:
    """Persistent state to avoid alert spam."""

    v12_low_active: bool = False
    offline_active: bool = False
    last_soh_percent: float | None = None


@dataclass
class AlertConfig:
    v12: V12AlertConfig = field(default_factory=V12AlertConfig)
    connect: ConnectAlertConfig = field(default_factory=ConnectAlertConfig)
    soh: SohAlertConfig = field(default_factory=SohAlertConfig)
    state: AlertState = field(default_factory=AlertState)


class BotSettingsStore:
    """Persists poll interval, alert rules, and alert state in data/bot_settings.json."""

    def __init__(self, path: Path, *, default_poll_interval: int) -> None:
        self._path = path
        self._default_poll_interval = default_poll_interval
        self.poll_interval = default_poll_interval
        self.alerts = AlertConfig()
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return

        try:
            self.poll_interval = int(
                raw.get("poll_interval_seconds", self._default_poll_interval)
            )
        except (TypeError, ValueError):
            self.poll_interval = self._default_poll_interval

        alerts_raw = raw.get("alerts")
        if isinstance(alerts_raw, dict):
            self.alerts = _parse_alert_config(alerts_raw)

        state_raw = raw.get("alert_state")
        if isinstance(state_raw, dict):
            self.alerts.state = _parse_alert_state(state_raw)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "poll_interval_seconds": self.poll_interval,
            "alerts": {
                "v12": {
                    "enabled": self.alerts.v12.enabled,
                    "threshold_v": self.alerts.v12.normalized_threshold(),
                },
                "connect": {
                    "enabled": self.alerts.connect.enabled,
                },
                "soh": {
                    "enabled": self.alerts.soh.enabled,
                },
            },
            "alert_state": {
                "v12_low_active": self.alerts.state.v12_low_active,
                "offline_active": self.alerts.state.offline_active,
                "last_soh_percent": self.alerts.state.last_soh_percent,
            },
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _parse_alert_config(raw: dict[str, Any]) -> AlertConfig:
    config = AlertConfig()
    v12_raw = raw.get("v12")
    if isinstance(v12_raw, dict):
        config.v12.enabled = bool(v12_raw.get("enabled", False))
        try:
            config.v12.threshold_v = float(v12_raw.get("threshold_v", DEFAULT_V12_THRESHOLD))
        except (TypeError, ValueError):
            config.v12.threshold_v = DEFAULT_V12_THRESHOLD

    connect_raw = raw.get("connect")
    if isinstance(connect_raw, dict):
        config.connect.enabled = bool(connect_raw.get("enabled", False))

    soh_raw = raw.get("soh")
    if isinstance(soh_raw, dict):
        config.soh.enabled = bool(soh_raw.get("enabled", False))
    return config


def _parse_alert_state(raw: dict[str, Any]) -> AlertState:
    last_soh: float | None = None
    if raw.get("last_soh_percent") is not None:
        try:
            last_soh = float(raw["last_soh_percent"])
        except (TypeError, ValueError):
            last_soh = None
    return AlertState(
        v12_low_active=bool(raw.get("v12_low_active", False)),
        offline_active=bool(raw.get("offline_active", False)),
        last_soh_percent=last_soh,
    )
