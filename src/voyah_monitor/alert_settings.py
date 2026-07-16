from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

V12_THRESHOLD_OPTIONS: tuple[float, ...] = (13.0, 12.8, 12.5, 12.0)
DEFAULT_V12_THRESHOLD = 12.5

CHARGE_TRIGGER_OPTIONS: tuple[int, ...] = (1, 5, 10)
DEFAULT_CHARGE_TRIGGER = 5
DEFAULT_CHARGE_MAX = 95
CHARGE_MAX_PRESETS: tuple[int, ...] = (80, 90, 95)


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
class ChargingAlertConfig:
    enabled: bool = False
    trigger_percent: int = DEFAULT_CHARGE_TRIGGER
    max_percent: int = DEFAULT_CHARGE_MAX

    def normalized_trigger(self) -> int:
        if self.trigger_percent in CHARGE_TRIGGER_OPTIONS:
            return self.trigger_percent
        return DEFAULT_CHARGE_TRIGGER

    def normalized_max(self) -> int:
        value = self.max_percent
        if isinstance(value, (int, float)):
            clamped = max(0, min(100, int(value)))
            return clamped
        return DEFAULT_CHARGE_MAX


@dataclass
class ChargingSessionState:
    active: bool = False
    last_notified_percent: float | None = None
    last_seen_percent: float | None = None
    points: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class AlertState:
    """Persistent state to avoid alert spam."""

    v12_low_active: bool = False
    offline_active: bool = False
    last_soh_percent: float | None = None
    charging_sessions: dict[str, ChargingSessionState] = field(default_factory=dict)


@dataclass
class AlertConfig:
    v12: V12AlertConfig = field(default_factory=V12AlertConfig)
    connect: ConnectAlertConfig = field(default_factory=ConnectAlertConfig)
    soh: SohAlertConfig = field(default_factory=SohAlertConfig)
    charging: ChargingAlertConfig = field(default_factory=ChargingAlertConfig)
    state: AlertState = field(default_factory=AlertState)


class BotSettingsStore:
    """Persists poll interval, alert rules, and alert state in data/bot_settings.json."""

    def __init__(self, path: Path, *, default_poll_interval: int) -> None:
        self._path = path
        self._default_poll_interval = default_poll_interval
        self.poll_interval = default_poll_interval
        self.alerts = AlertConfig()
        # exp_unix_str -> list of days_left already notified (1/2/3)
        self.session_expiry_notified: dict[str, list[int]] = {}
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

        expiry_raw = raw.get("session_expiry_notified")
        if isinstance(expiry_raw, dict):
            parsed: dict[str, list[int]] = {}
            for key, days in expiry_raw.items():
                if isinstance(days, list):
                    parsed[str(key)] = [
                        int(day) for day in days if isinstance(day, (int, float))
                    ]
            self.session_expiry_notified = parsed

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
                "charging": {
                    "enabled": self.alerts.charging.enabled,
                    "trigger_percent": self.alerts.charging.normalized_trigger(),
                    "max_percent": self.alerts.charging.normalized_max(),
                },
            },
            "alert_state": _serialize_alert_state(self.alerts.state),
            "session_expiry_notified": self.session_expiry_notified,
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _serialize_alert_state(state: AlertState) -> dict[str, Any]:
    sessions: dict[str, Any] = {}
    for key, session in state.charging_sessions.items():
        sessions[key] = {
            "active": session.active,
            "last_notified_percent": session.last_notified_percent,
            "last_seen_percent": session.last_seen_percent,
            "points": [[ts, soc] for ts, soc in session.points],
        }
    return {
        "v12_low_active": state.v12_low_active,
        "offline_active": state.offline_active,
        "last_soh_percent": state.last_soh_percent,
        "charging_sessions": sessions,
    }


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

    charging_raw = raw.get("charging")
    if isinstance(charging_raw, dict):
        config.charging.enabled = bool(charging_raw.get("enabled", False))
        try:
            config.charging.trigger_percent = int(
                charging_raw.get("trigger_percent", DEFAULT_CHARGE_TRIGGER)
            )
        except (TypeError, ValueError):
            config.charging.trigger_percent = DEFAULT_CHARGE_TRIGGER
        try:
            config.charging.max_percent = int(
                charging_raw.get("max_percent", DEFAULT_CHARGE_MAX)
            )
        except (TypeError, ValueError):
            config.charging.max_percent = DEFAULT_CHARGE_MAX

    return config


def _parse_charging_session(raw: dict[str, Any]) -> ChargingSessionState:
    points: list[tuple[str, float]] = []
    raw_points = raw.get("points")
    if isinstance(raw_points, list):
        for item in raw_points:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                try:
                    points.append((str(item[0]), float(item[1])))
                except (TypeError, ValueError):
                    continue
    last_notified: float | None = None
    if raw.get("last_notified_percent") is not None:
        try:
            last_notified = float(raw["last_notified_percent"])
        except (TypeError, ValueError):
            last_notified = None
    last_seen: float | None = None
    if raw.get("last_seen_percent") is not None:
        try:
            last_seen = float(raw["last_seen_percent"])
        except (TypeError, ValueError):
            last_seen = None
    return ChargingSessionState(
        active=bool(raw.get("active", False)),
        last_notified_percent=last_notified,
        last_seen_percent=last_seen,
        points=points,
    )


def _parse_alert_state(raw: dict[str, Any]) -> AlertState:
    last_soh: float | None = None
    if raw.get("last_soh_percent") is not None:
        try:
            last_soh = float(raw["last_soh_percent"])
        except (TypeError, ValueError):
            last_soh = None

    charging_sessions: dict[str, ChargingSessionState] = {}
    sessions_raw = raw.get("charging_sessions")
    if isinstance(sessions_raw, dict):
        for key, session_raw in sessions_raw.items():
            if isinstance(session_raw, dict):
                charging_sessions[str(key)] = _parse_charging_session(session_raw)

    return AlertState(
        v12_low_active=bool(raw.get("v12_low_active", False)),
        offline_active=bool(raw.get("offline_active", False)),
        last_soh_percent=last_soh,
        charging_sessions=charging_sessions,
    )
