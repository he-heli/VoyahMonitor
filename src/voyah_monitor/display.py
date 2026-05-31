from __future__ import annotations

import json

from voyah_monitor.storage import DailyMileage, SnapshotRecord
from voyah_monitor.telemetry import VehicleTelemetry


def _format_value(label: str, value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return f"{label}: {'да' if value else 'нет'}"
    if isinstance(value, float):
        return f"{label}: {value:g}"
    return f"{label}: {value}"


def format_snapshot_record(record: SnapshotRecord) -> str:
    telemetry = record.telemetry
    lines = [
        f"[#{record.id}] vehicle_key={record.vehicle_key}",
        f"Время: {telemetry.captured_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    for label, value in (
        ("vehicle_id", telemetry.vehicle_id),
        ("Автомобиль", telemetry.name),
        ("VIN", telemetry.vin),
        ("Пробег, км", telemetry.odometer_km),
        ("Заряд, %", telemetry.battery_percent),
        ("Запас хода, км", telemetry.range_km),
        ("Скорость, км/ч", telemetry.speed_kmh),
        ("Широта", telemetry.latitude),
        ("Долгота", telemetry.longitude),
        ("Статус", telemetry.status),
        ("Зарядка", telemetry.is_charging),
    ):
        formatted = _format_value(label, value)
        if formatted:
            lines.append(formatted)

    lines.append("raw_json:")
    lines.append(json.dumps(telemetry.raw, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def format_daily_mileage_record(record: DailyMileage) -> str:
    return (
        f"day={record.day.isoformat()} "
        f"vehicle_key={record.vehicle_key} "
        f"start={record.start_odometer_km:g} km "
        f"end={record.end_odometer_km:g} km "
        f"distance={record.distance_km:g} km"
    )


def format_database_status(
    snapshots: list[SnapshotRecord],
    mileage_rows: list[DailyMileage],
) -> str:
    sections: list[str] = []

    sections.append(f"=== telemetry_snapshots ({len(snapshots)}) ===")
    if snapshots:
        for index, snapshot in enumerate(snapshots, start=1):
            sections.append(f"--- snapshot {index}/{len(snapshots)} ---")
            sections.append(format_snapshot_record(snapshot))
    else:
        sections.append("(пусто)")

    sections.append("")
    sections.append(f"=== daily_mileage ({len(mileage_rows)}) ===")
    if mileage_rows:
        for row in mileage_rows:
            sections.append(format_daily_mileage_record(row))
    else:
        sections.append("(пусто)")

    return "\n".join(sections)
