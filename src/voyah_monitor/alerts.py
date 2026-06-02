from __future__ import annotations

from dataclasses import dataclass

from voyah_monitor.alert_settings import AlertConfig, AlertState
from voyah_monitor.telemetry import VehicleTelemetry


@dataclass(frozen=True)
class AlertNotification:
    kind: str
    text: str


def evaluate_alerts(
    telemetry: VehicleTelemetry,
    config: AlertConfig,
) -> tuple[list[AlertNotification], AlertState]:
    """Return notifications and updated state after one telemetry reading."""
    messages: list[AlertNotification] = []
    state = AlertState(
        v12_low_active=config.state.v12_low_active,
        offline_active=config.state.offline_active,
        last_soh_percent=config.state.last_soh_percent,
    )
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

    return messages, state


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
