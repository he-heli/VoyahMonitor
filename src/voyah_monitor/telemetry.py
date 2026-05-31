from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class VehicleTelemetry(BaseModel):
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    vehicle_id: str | None = None
    vin: str | None = None
    name: str | None = None
    odometer_km: float | None = None
    battery_percent: float | None = None
    range_km: float | None = None
    speed_kmh: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    course_deg: float | None = None
    soh_percent: float | None = None
    is_online: bool | None = None
    location_sharing: bool | None = None
    status: str | None = None
    is_charging: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


def _first_match(data: dict[str, Any], *keys: str) -> Any:
    lowered = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] is not None:
            return lowered[key.lower()]
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^\d.,-]", "", value).replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "charging", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return None


def normalize_record(record: dict[str, Any]) -> VehicleTelemetry:
    vehicle_id = _first_match(record, "vehicleId", "vehicle_id", "id", "carId", "car_id", "_id")
    vin = _first_match(record, "vin", "VIN")
    name = _first_match(record, "name", "title", "model", "plate", "licensePlate", "displayName")
    if not name and isinstance(record.get("carModel"), dict):
        model = record["carModel"]
        name = model.get("displayName") or model.get("name")

    odometer = _to_float(
        _first_match(record, "odometer", "mileage", "totalMileage", "total_mileage", "km")
    )
    lat = _to_float(_first_match(record, "latitude", "lat"))
    lon = _to_float(_first_match(record, "longitude", "lng", "lon"))
    battery = _to_float(
        _first_match(record, "soc", "battery", "batteryLevel", "battery_percent", "charge")
    )
    range_km = _to_float(_first_match(record, "range", "remainingRange", "range_km"))
    speed = _to_float(_first_match(record, "speed", "speedKmh", "speed_kmh", "course"))

    status = _first_match(record, "status", "state", "vehicleStatus")
    charging = _to_bool(_first_match(record, "isCharging", "charging", "chargeStatus"))

    return VehicleTelemetry(
        vehicle_id=str(vehicle_id) if vehicle_id is not None else None,
        vin=str(vin) if vin is not None else None,
        name=str(name) if name is not None else None,
        odometer_km=odometer,
        battery_percent=battery,
        range_km=range_km,
        speed_kmh=speed,
        latitude=lat,
        longitude=lon,
        status=str(status) if status is not None else None,
        is_charging=charging,
        raw=record,
    )


def normalize_payload(payload: Any) -> list[VehicleTelemetry]:
    from voyah_monitor.client import extract_telemetry_candidates

    records = extract_telemetry_candidates(payload)
    if not records and isinstance(payload, dict):
        records = [payload]
    normalized = [normalize_record(record) for record in records]
    # Deduplicate by vehicle_id/vin while preserving order
    seen: set[str] = set()
    unique: list[VehicleTelemetry] = []
    for item in normalized:
        key = item.vehicle_id or item.vin or str(hash(str(item.raw)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def format_status(telemetry: VehicleTelemetry) -> str:
    lines = [
        f"Время: {telemetry.captured_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    if telemetry.name:
        lines.append(f"Автомобиль: {telemetry.name}")
    if telemetry.vin:
        lines.append(f"VIN: {telemetry.vin}")
    if telemetry.odometer_km is not None:
        lines.append(f"Пробег: {telemetry.odometer_km:.1f} км")
    if telemetry.battery_percent is not None:
        lines.append(f"Заряд: {telemetry.battery_percent:.0f}%")
    if telemetry.range_km is not None:
        lines.append(f"Запас хода: {telemetry.range_km:.0f} км")
    if telemetry.status:
        lines.append(f"Статус: {telemetry.status}")
    if telemetry.is_charging is not None:
        lines.append("Зарядка: да" if telemetry.is_charging else "Зарядка: нет")
    if telemetry.latitude is not None and telemetry.longitude is not None:
        lines.append(f"Координаты: {telemetry.latitude:.5f}, {telemetry.longitude:.5f}")
    if telemetry.course_deg is not None:
        lines.append(f"Курс: {telemetry.course_deg:g}°")
    if telemetry.soh_percent is not None:
        lines.append(f"SOH: {telemetry.soh_percent:g}%")
    if telemetry.is_online is not None:
        lines.append("На связи: да" if telemetry.is_online else "На связи: нет")
    if telemetry.location_sharing is not None:
        lines.append(
            "Передача геопозиции: да" if telemetry.location_sharing else "Передача геопозиции: нет"
        )
    return "\n".join(lines)


def dashboard_items_to_telemetry(items: list[dict[str, Any]]) -> list[VehicleTelemetry]:
    from voyah_monitor.vehicle_status import dashboard_item_to_telemetry

    return [dashboard_item_to_telemetry(item) for item in items if isinstance(item, dict)]
