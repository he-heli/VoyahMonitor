from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font

from voyah_monitor.storage import DailyMileage, SnapshotRecord, TelemetryStorage
from voyah_monitor.vehicle_status import SNAPSHOT_EXPORT_DATA_HEADERS, snapshot_export_field_map


def _export_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "да" if value else "нет"
    return value


def _snapshot_row(record: SnapshotRecord) -> list[Any]:
    telemetry = record.telemetry
    captured_local = telemetry.captured_at.astimezone()
    fields = snapshot_export_field_map(telemetry)
    return [
        record.id,
        captured_local.strftime("%Y-%m-%d %H:%M:%S"),
        *[_export_cell(fields.get(header)) for header in SNAPSHOT_EXPORT_DATA_HEADERS],
    ]


SNAPSHOT_HEADERS = ("ID", "Время") + SNAPSHOT_EXPORT_DATA_HEADERS

MILEAGE_HEADERS = (
    "День",
    "Автомобиль",
    "Пробег начало, км",
    "Пробег конец, км",
    "Пробег за день, км",
)


def _mileage_row(row: DailyMileage) -> list[Any]:
    return [
        row.day.isoformat(),
        row.vehicle_key,
        row.start_odometer_km,
        row.end_odometer_km,
        row.distance_km,
    ]


def _autosize_sheet(ws: Any) -> None:
    for column_cells in ws.columns:
        letter = column_cells[0].column_letter
        max_length = 0
        for cell in column_cells:
            if cell.value is not None:
                max_length = max(max_length, len(str(cell.value)))
        ws.column_dimensions[letter].width = min(max_length + 2, 40)


def export_history_xlsx(
    storage: TelemetryStorage,
    *,
    days: int | None = None,
    snapshots: list[SnapshotRecord] | None = None,
) -> bytes:
    if snapshots is None:
        snapshots = storage.snapshots_in_range(days=days)
    mileage_rows = _filter_mileage(storage.all_daily_mileage(), days=days)

    workbook = Workbook()
    snapshots_sheet = workbook.active
    snapshots_sheet.title = "Снимки"
    snapshots_sheet.append(SNAPSHOT_HEADERS)
    for cell in snapshots_sheet[1]:
        cell.font = Font(bold=True)
    for record in snapshots:
        snapshots_sheet.append(_snapshot_row(record))
    if len(snapshots) <= 200:
        _autosize_sheet(snapshots_sheet)

    mileage_sheet = workbook.create_sheet("Пробег по дням")
    mileage_sheet.append(MILEAGE_HEADERS)
    for cell in mileage_sheet[1]:
        cell.font = Font(bold=True)
    for row in mileage_rows:
        mileage_sheet.append(_mileage_row(row))
    if len(mileage_rows) <= 200:
        _autosize_sheet(mileage_sheet)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def export_filename(*, days: int | None = None) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M")
    if days is None:
        return f"voyah_history_all_{stamp}.xlsx"
    return f"voyah_history_{days}d_{stamp}.xlsx"


def period_label(days: int | None) -> str:
    if days is None:
        return "за всё время"
    if days == 1:
        return "за 1 день"
    if days % 30 == 0 and days >= 30:
        months = days // 30
        return f"за {months} мес."
    return f"за {days} дн."


def _filter_mileage(rows: list[DailyMileage], *, days: int | None) -> list[DailyMileage]:
    if days is None:
        return rows
    cutoff = datetime.now().astimezone().date()
    from datetime import timedelta

    min_day = cutoff - timedelta(days=days)
    return [row for row in rows if row.day >= min_day]
