from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from voyah_monitor.alert_settings import (
    AlertConfig,
    AlertState,
    ChargingSessionState,
)
from voyah_monitor.charging_chart import parse_point_timestamp, render_charging_chart
from voyah_monitor.telemetry import VehicleTelemetry
from voyah_monitor.timeutil import format_moscow


@dataclass(frozen=True)
class AlertNotification:
    kind: str
    text: str
    photo_png: bytes | None = None


def evaluate_alerts(
    telemetry: VehicleTelemetry,
    config: AlertConfig,
) -> tuple[list[AlertNotification], AlertState]:
    """Return notifications and updated state after one telemetry reading."""
    messages: list[AlertNotification] = []
    state = copy.deepcopy(config.state)
    car = telemetry.name or telemetry.vin or "Автомобиль"

    if config.v12.enabled:
        messages.extend(_evaluate_v12(telemetry, config, state, car))
    elif state.v12_low_active:
        state.v12_low_active = False

    if config.connect.enabled:
        messages.extend(_evaluate_connect(telemetry, state, car))
    elif state.offline_active:
        state.offline_active = False

    if config.soh.enabled:
        messages.extend(_evaluate_soh(telemetry, state, car))
    elif state.last_soh_percent is not None:
        state.last_soh_percent = None

    if config.charging.enabled:
        messages.extend(_evaluate_charging(telemetry, config, state, car))
    elif state.charging_sessions:
        state.charging_sessions.clear()

    return messages, state


def _vehicle_key(telemetry: VehicleTelemetry) -> str:
    return telemetry.vehicle_id or telemetry.vin or "default"


def _format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        if minutes > 0:
            return f"{hours} ч {minutes} мин"
        return f"{hours} ч"
    if minutes > 0:
        if secs > 0:
            return f"{minutes} мин {secs} сек"
        return f"{minutes} мин"
    return f"{secs} сек"


def _format_moscow_time(when: datetime) -> str:
    return format_moscow(when, fmt="%d.%m.%Y %H:%M")


def _sec_per_percent(points: list[tuple[str, float]]) -> float | None:
    if len(points) < 2:
        return None
    first_ts, first_soc = points[0]
    last_ts, last_soc = points[-1]
    delta_soc = last_soc - first_soc
    if delta_soc <= 0:
        return None
    start = parse_point_timestamp(first_ts)
    end = parse_point_timestamp(last_ts)
    delta_seconds = (end - start).total_seconds()
    if delta_seconds <= 0:
        return None
    return delta_seconds / delta_soc


def _charging_metrics(
    points: list[tuple[str, float]],
    *,
    current_soc: float,
    max_percent: float,
    now: datetime,
) -> tuple[float | None, timedelta | None, datetime | None]:
    sec_per_pct = _sec_per_percent(points)
    if sec_per_pct is None:
        return None, None, None
    remaining = max(0.0, max_percent - current_soc)
    if remaining <= 0:
        return sec_per_pct, timedelta(0), now
    eta = timedelta(seconds=remaining * sec_per_pct)
    finish = now + eta
    return sec_per_pct, eta, finish


def _build_charging_notification(
    *,
    car: str,
    current_soc: float,
    max_percent: float,
    points: list[tuple[str, float]],
    now: datetime,
    final: bool = False,
) -> AlertNotification:
    sec_per_pct, eta, finish = _charging_metrics(
        points,
        current_soc=current_soc,
        max_percent=max_percent,
        now=now,
    )

    parsed_points = [(parse_point_timestamp(ts), soc) for ts, soc in points]

    lines = [f"⚡ {car} — зарядка", f"Заряд: {current_soc:g}%"]
    if sec_per_pct is not None:
        lines.append(f"Скорость: ~{_format_duration(sec_per_pct)} на 1%")
    if eta is not None and finish is not None and current_soc < max_percent:
        lines.append(f"До {max_percent}%: ~{_format_duration(eta.total_seconds())}")
        lines.append(f"Окончание (~МСК): {_format_moscow_time(finish)}")
    if final:
        lines.append(f"Цель {max_percent}% достигнута.")

    photo: bytes | None = None
    if parsed_points:
        try:
            photo = render_charging_chart(
                parsed_points,
                max_percent=max_percent,
                forecast_end=finish,
                current_soc=current_soc,
            )
        except Exception:
            photo = None

    kind = "charge_complete" if final else "charge_progress"
    return AlertNotification(kind=kind, text="\n".join(lines), photo_png=photo)


def _charging_detected(
    telemetry: VehicleTelemetry,
    session: ChargingSessionState,
    soc: float,
) -> bool:
    if telemetry.is_charging is True:
        return True
    if session.last_seen_percent is not None and soc > session.last_seen_percent:
        return True
    return False


def _charging_stopped(
    telemetry: VehicleTelemetry,
    session: ChargingSessionState,
) -> bool:
    if telemetry.is_charging is False:
        return True
    soc = telemetry.battery_percent
    if soc is None or session.last_seen_percent is None:
        return False
    return soc < session.last_seen_percent


def _evaluate_charging(
    telemetry: VehicleTelemetry,
    config: AlertConfig,
    state: AlertState,
    car: str,
) -> list[AlertNotification]:
    messages: list[AlertNotification] = []
    soc = telemetry.battery_percent
    if soc is None:
        return messages

    vehicle_key = _vehicle_key(telemetry)
    session = state.charging_sessions.get(vehicle_key)
    if session is None:
        session = ChargingSessionState()
        state.charging_sessions[vehicle_key] = session

    max_percent = config.charging.normalized_max()
    trigger = config.charging.normalized_trigger()
    now = telemetry.captured_at
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)
    ts = now.isoformat()

    if not session.active:
        if not _charging_detected(telemetry, session, soc):
            session.last_seen_percent = soc
            return messages
        session.active = True
        session.last_notified_percent = soc
        session.last_seen_percent = soc
        session.points = [(ts, soc)]
        return messages

    if _charging_stopped(telemetry, session):
        state.charging_sessions.pop(vehicle_key, None)
        return messages

    if not session.points or session.points[-1][1] != soc or session.points[-1][0] != ts:
        session.points.append((ts, soc))
    session.last_seen_percent = soc

    if soc >= max_percent:
        messages.append(
            _build_charging_notification(
                car=car,
                current_soc=soc,
                max_percent=max_percent,
                points=session.points,
                now=now,
                final=True,
            )
        )
        state.charging_sessions.pop(vehicle_key, None)
        return messages

    baseline = session.last_notified_percent
    if baseline is not None and soc >= baseline + trigger:
        messages.append(
            _build_charging_notification(
                car=car,
                current_soc=soc,
                max_percent=max_percent,
                points=session.points,
                now=now,
            )
        )
        session.last_notified_percent = soc

    return messages


def _evaluate_v12(
    telemetry: VehicleTelemetry,
    config: AlertConfig,
    state: AlertState,
    car: str,
) -> list[AlertNotification]:
    messages: list[AlertNotification] = []
    voltage = telemetry.v12_voltage
    threshold = config.v12.normalized_threshold()

    if voltage is None:
        return messages

    if voltage < threshold:
        if not state.v12_low_active:
            state.v12_low_active = True
            messages.append(
                AlertNotification(
                    kind="v12_low",
                    text=(
                        f"⚠️ {car}\n"
                        f"Батарея 12V: {voltage:g} V (порог {threshold:g} V)"
                    ),
                )
            )
    elif state.v12_low_active:
        state.v12_low_active = False
        messages.append(
            AlertNotification(
                kind="v12_ok",
                text=(
                    f"✅ {car}\n"
                    f"Батарея 12V восстановилась: {voltage:g} V"
                ),
            )
        )

    return messages


def _evaluate_connect(
    telemetry: VehicleTelemetry,
    state: AlertState,
    car: str,
) -> list[AlertNotification]:
    messages: list[AlertNotification] = []
    online = telemetry.is_online

    if online is False:
        if not state.offline_active:
            state.offline_active = True
            messages.append(
                AlertNotification(
                    kind="offline",
                    text=f"⚠️ {car}\nАвтомобиль не на связи",
                )
            )
    elif online is True and state.offline_active:
        state.offline_active = False
        messages.append(
            AlertNotification(
                kind="online",
                text=f"✅ {car}\nАвтомобиль снова на связи",
            )
        )

    return messages


def _soh_values_differ(previous: float, current: float) -> bool:
    return round(previous, 2) != round(current, 2)


def _evaluate_soh(
    telemetry: VehicleTelemetry,
    state: AlertState,
    car: str,
) -> list[AlertNotification]:
    messages: list[AlertNotification] = []
    soh = telemetry.soh_percent

    if soh is None:
        return messages

    if state.last_soh_percent is None:
        state.last_soh_percent = soh
        return messages

    if _soh_values_differ(state.last_soh_percent, soh):
        previous = state.last_soh_percent
        state.last_soh_percent = soh
        messages.append(
            AlertNotification(
                kind="soh_change",
                text=(
                    f"⚠️ {car}\n"
                    f"SOH изменился: {previous:g}% → {soh:g}%"
                ),
            )
        )

    return messages
