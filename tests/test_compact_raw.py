from __future__ import annotations

import json

from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import VehicleTelemetry
from voyah_monitor.vehicle_status import compact_dashboard_raw, merge_dashboard_export_fields


def _dashboard_raw() -> dict:
    return {
        "table": {
            "vin": "VIN1",
            "licensePlate": "А123АА777",
            "carModel": {"displayName": "Test Car", "modname": "EV"},
            "liveSensors": {
                "fuelPercentage": 45.0,
                "remainsMileageFuel": 320.0,
                "batteryPercentage": 70.0,
                "remainsMileage": 280.0,
                "odometer": 1000.0,
                "soh": 100.0,
                "12VBatteryVoltage": 12.8,
            },
        },
        "geo": {},
        "detail": {},
        "tbox": {
            "isOnline": True,
            "sensors": {"chip": {"title": "Доступен"}},
        },
    }


def _bloated_dashboard_raw() -> dict:
    raw = _dashboard_raw()
    raw["tbox"]["buttons"] = {"unused": "x" * 70_000}
    raw["tbox"]["automations"] = {"list": list(range(100))}
    return raw


def test_compact_dashboard_raw_drops_unused_bulk() -> None:
    raw = _bloated_dashboard_raw()
    compacted = compact_dashboard_raw(raw)
    blob = json.dumps(compacted, ensure_ascii=False)
    assert len(blob) < 10_000
    assert "buttons" not in compacted.get("tbox", {})
    assert merge_dashboard_export_fields(raw) == merge_dashboard_export_fields(compacted)


def test_save_snapshot_stores_compact_raw(tmp_path) -> None:
    storage = TelemetryStorage(tmp_path / "test.db")
    raw = _bloated_dashboard_raw()
    storage.save_snapshot(
        VehicleTelemetry(
            vehicle_id="car1",
            vin="VIN1",
            raw=raw,
        )
    )
    with storage._connect() as conn:
        row = conn.execute("SELECT raw_json FROM telemetry_snapshots").fetchone()
    assert row is not None
    stored = json.loads(row["raw_json"])
    assert len(row["raw_json"]) < 10_000
    assert "buttons" not in stored.get("tbox", {})


def test_compact_stored_raw_json_shrinks_database(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    storage = TelemetryStorage(db_path)
    for _ in range(3):
        storage.save_snapshot(
            VehicleTelemetry(
                vehicle_id="car1",
                raw=_bloated_dashboard_raw(),
            )
        )
    # Simulate legacy fat rows
    with storage._connect() as conn:
        fat = json.dumps(_bloated_dashboard_raw(), ensure_ascii=False)
        conn.execute("UPDATE telemetry_snapshots SET raw_json = ?", (fat,))

    before = db_path.stat().st_size
    updated, _ = storage.compact_stored_raw_json()
    after = db_path.stat().st_size
    assert updated == 3
    assert after < before
