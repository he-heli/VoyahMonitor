from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from voyah_monitor.telemetry import VehicleTelemetry
from voyah_monitor.timeutil import moscow_date
from voyah_monitor.vehicle_status import compact_dashboard_raw, is_dashboard_snapshot_raw


@dataclass
class SnapshotRecord:
    id: int
    vehicle_key: str
    telemetry: VehicleTelemetry


@dataclass
class DailyMileage:
    day: date
    vehicle_key: str
    start_odometer_km: float
    end_odometer_km: float

    @property
    def distance_km(self) -> float:
        return max(0.0, self.end_odometer_km - self.start_odometer_km)


class TelemetryStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS telemetry_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    captured_at TEXT NOT NULL,
                    vehicle_key TEXT NOT NULL,
                    vehicle_id TEXT,
                    vin TEXT,
                    name TEXT,
                    odometer_km REAL,
                    battery_percent REAL,
                    range_km REAL,
                    speed_kmh REAL,
                    latitude REAL,
                    longitude REAL,
                    course_deg REAL,
                    soh_percent REAL,
                    is_online INTEGER,
                    location_sharing INTEGER,
                    status TEXT,
                    is_charging INTEGER,
                    v12_voltage REAL,
                    raw_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_snapshots_vehicle_time
                    ON telemetry_snapshots (vehicle_key, captured_at DESC);

                CREATE TABLE IF NOT EXISTS daily_mileage (
                    day TEXT NOT NULL,
                    vehicle_key TEXT NOT NULL,
                    start_odometer_km REAL NOT NULL,
                    end_odometer_km REAL NOT NULL,
                    distance_km REAL NOT NULL,
                    PRIMARY KEY (day, vehicle_key)
                );
                """
            )
            self._ensure_columns(
                conn,
                "telemetry_snapshots",
                {
                    "course_deg": "REAL",
                    "soh_percent": "REAL",
                    "is_online": "INTEGER",
                    "location_sharing": "INTEGER",
                    "v12_voltage": "REAL",
                },
            )

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {
            row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def vehicle_key(telemetry: VehicleTelemetry) -> str:
        return telemetry.vehicle_id or telemetry.vin or telemetry.name or "unknown"

    def save_snapshot(self, telemetry: VehicleTelemetry) -> None:
        key = self.vehicle_key(telemetry)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO telemetry_snapshots (
                    captured_at, vehicle_key, vehicle_id, vin, name,
                    odometer_km, battery_percent, range_km, speed_kmh,
                    latitude, longitude, course_deg, soh_percent, is_online,
                    location_sharing, status, is_charging, v12_voltage, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    telemetry.captured_at.isoformat(),
                    key,
                    telemetry.vehicle_id,
                    telemetry.vin,
                    telemetry.name,
                    telemetry.odometer_km,
                    telemetry.battery_percent,
                    telemetry.range_km,
                    telemetry.speed_kmh,
                    telemetry.latitude,
                    telemetry.longitude,
                    telemetry.course_deg,
                    telemetry.soh_percent,
                    1 if telemetry.is_online else 0 if telemetry.is_online is not None else None,
                    1
                    if telemetry.location_sharing
                    else 0
                    if telemetry.location_sharing is not None
                    else None,
                    telemetry.status,
                    1 if telemetry.is_charging else 0 if telemetry.is_charging is not None else None,
                    telemetry.v12_voltage,
                    json.dumps(self._persisted_raw(telemetry.raw), ensure_ascii=False),
                ),
            )
            self._update_daily_mileage(conn, key, telemetry)

    @staticmethod
    def _persisted_raw(raw: dict) -> dict:
        if is_dashboard_snapshot_raw(raw):
            return compact_dashboard_raw(raw)
        return raw

    def _update_daily_mileage(
        self,
        conn: sqlite3.Connection,
        vehicle_key: str,
        telemetry: VehicleTelemetry,
    ) -> None:
        if telemetry.odometer_km is None:
            return

        day = moscow_date(telemetry.captured_at).isoformat()
        row = conn.execute(
            "SELECT start_odometer_km, end_odometer_km FROM daily_mileage WHERE day = ? AND vehicle_key = ?",
            (day, vehicle_key),
        ).fetchone()

        if row is None:
            conn.execute(
                """
                INSERT INTO daily_mileage (day, vehicle_key, start_odometer_km, end_odometer_km, distance_km)
                VALUES (?, ?, ?, ?, ?)
                """,
                (day, vehicle_key, telemetry.odometer_km, telemetry.odometer_km, 0.0),
            )
            return

        start_odometer = row["start_odometer_km"]
        end_odometer = max(row["end_odometer_km"], telemetry.odometer_km)
        distance = max(0.0, end_odometer - start_odometer)
        conn.execute(
            """
            UPDATE daily_mileage
            SET end_odometer_km = ?, distance_km = ?
            WHERE day = ? AND vehicle_key = ?
            """,
            (end_odometer, distance, day, vehicle_key),
        )

    def _row_to_telemetry(self, row: sqlite3.Row) -> VehicleTelemetry:
        return VehicleTelemetry(
            captured_at=datetime.fromisoformat(row["captured_at"]),
            vehicle_id=row["vehicle_id"],
            vin=row["vin"],
            name=row["name"],
            odometer_km=row["odometer_km"],
            battery_percent=row["battery_percent"],
            range_km=row["range_km"],
            speed_kmh=row["speed_kmh"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            course_deg=row["course_deg"] if "course_deg" in row.keys() else None,
            soh_percent=row["soh_percent"] if "soh_percent" in row.keys() else None,
            v12_voltage=row["v12_voltage"] if "v12_voltage" in row.keys() else None,
            is_online=bool(row["is_online"]) if "is_online" in row.keys() and row["is_online"] is not None else None,
            location_sharing=bool(row["location_sharing"])
            if "location_sharing" in row.keys() and row["location_sharing"] is not None
            else None,
            status=row["status"],
            is_charging=bool(row["is_charging"]) if row["is_charging"] is not None else None,
            raw=json.loads(row["raw_json"]),
        )

    @staticmethod
    def _cutoff_iso(days: int) -> str:
        return (datetime.now(UTC) - timedelta(days=days)).isoformat()

    def _snapshots_where(
        self,
        *,
        days: int | None = None,
        vehicle_key: str | None = None,
    ) -> tuple[str, list[object]]:
        where_parts: list[str] = []
        params: list[object] = []
        if vehicle_key:
            where_parts.append("vehicle_key = ?")
            params.append(vehicle_key)
        if days is not None:
            where_parts.append("captured_at >= ?")
            params.append(self._cutoff_iso(days))
        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        return where, params

    def snapshots_count_in_range(
        self,
        *,
        days: int | None = None,
        vehicle_key: str | None = None,
    ) -> int:
        where, params = self._snapshots_where(days=days, vehicle_key=vehicle_key)
        query = f"SELECT COUNT(*) AS count FROM telemetry_snapshots {where}"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["count"]) if row else 0

    def iter_snapshots_in_range(
        self,
        *,
        days: int | None = None,
        vehicle_key: str | None = None,
    ) -> Iterator[SnapshotRecord]:
        where, params = self._snapshots_where(days=days, vehicle_key=vehicle_key)
        query = f"""
            SELECT * FROM telemetry_snapshots
            {where}
            ORDER BY captured_at ASC, id ASC
        """
        with self._connect() as conn:
            cursor = conn.execute(query, params)
            for row in cursor:
                yield SnapshotRecord(
                    id=row["id"],
                    vehicle_key=row["vehicle_key"],
                    telemetry=self._row_to_telemetry(row),
                )

    def snapshots_in_range(
        self,
        *,
        days: int | None = None,
        vehicle_key: str | None = None,
    ) -> list[SnapshotRecord]:
        return list(self.iter_snapshots_in_range(days=days, vehicle_key=vehicle_key))

    def compact_stored_raw_json(self) -> tuple[int, int]:
        """Rewrite raw_json blobs to slim form. Returns (updated_rows, bytes_before)."""
        bytes_before = 0
        updated = 0
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT id, raw_json FROM telemetry_snapshots ORDER BY id ASC"
            )
            for row in cursor:
                raw = json.loads(row["raw_json"])
                if not is_dashboard_snapshot_raw(raw):
                    continue
                compacted = compact_dashboard_raw(raw)
                old_size = len(row["raw_json"])
                new_blob = json.dumps(compacted, ensure_ascii=False)
                if new_blob == row["raw_json"]:
                    continue
                bytes_before += old_size
                conn.execute(
                    "UPDATE telemetry_snapshots SET raw_json = ? WHERE id = ?",
                    (new_blob, row["id"]),
                )
                updated += 1
        if updated:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("VACUUM")
        return updated, bytes_before

    def all_snapshots(self, vehicle_key: str | None = None) -> list[SnapshotRecord]:
        query = """
            SELECT * FROM telemetry_snapshots
            {where}
            ORDER BY captured_at ASC, id ASC
        """
        params: tuple[object, ...] = ()
        where = ""
        if vehicle_key:
            where = "WHERE vehicle_key = ?"
            params = (vehicle_key,)

        with self._connect() as conn:
            rows = conn.execute(query.format(where=where), params).fetchall()

        return [
            SnapshotRecord(
                id=row["id"],
                vehicle_key=row["vehicle_key"],
                telemetry=self._row_to_telemetry(row),
            )
            for row in rows
        ]

    def snapshot_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM telemetry_snapshots").fetchone()
            return int(row["count"]) if row else 0

    def latest_snapshot(self, vehicle_key: str | None = None) -> VehicleTelemetry | None:
        query = """
            SELECT * FROM telemetry_snapshots
            {where}
            ORDER BY captured_at DESC
            LIMIT 1
        """
        params: tuple[object, ...] = ()
        where = ""
        if vehicle_key:
            where = "WHERE vehicle_key = ?"
            params = (vehicle_key,)

        with self._connect() as conn:
            row = conn.execute(query.format(where=where), params).fetchone()
            if not row:
                return None
            return self._row_to_telemetry(row)

    def all_daily_mileage(self, vehicle_key: str | None = None) -> list[DailyMileage]:
        query = """
            SELECT day, vehicle_key, start_odometer_km, end_odometer_km, distance_km
            FROM daily_mileage
            {where}
            ORDER BY day ASC, vehicle_key ASC
        """
        params: tuple[object, ...] = ()
        where = ""
        if vehicle_key:
            where = "WHERE vehicle_key = ?"
            params = (vehicle_key,)

        with self._connect() as conn:
            rows = conn.execute(query.format(where=where), params).fetchall()

        return [
            DailyMileage(
                day=date.fromisoformat(row["day"]),
                vehicle_key=row["vehicle_key"],
                start_odometer_km=row["start_odometer_km"],
                end_odometer_km=row["end_odometer_km"],
            )
            for row in rows
        ]

    def daily_mileage_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM daily_mileage").fetchone()
            return int(row["count"]) if row else 0

    def daily_mileage(self, days: int = 14, vehicle_key: str | None = None) -> list[DailyMileage]:
        query = """
            SELECT day, vehicle_key, start_odometer_km, end_odometer_km, distance_km
            FROM daily_mileage
            {where}
            ORDER BY day DESC
            LIMIT ?
        """
        params: list[object] = []
        where = ""
        if vehicle_key:
            where = "WHERE vehicle_key = ?"
            params.append(vehicle_key)
        params.append(days)

        with self._connect() as conn:
            rows = conn.execute(query.format(where=where), params).fetchall()

        return [
            DailyMileage(
                day=date.fromisoformat(row["day"]),
                vehicle_key=row["vehicle_key"],
                start_odometer_km=row["start_odometer_km"],
                end_odometer_km=row["end_odometer_km"],
            )
            for row in rows
        ]

    def battery_history(self, days: int = 7, vehicle_key: str | None = None) -> list[tuple[datetime, float]]:
        query = """
            SELECT captured_at, battery_percent
            FROM telemetry_snapshots
            WHERE battery_percent IS NOT NULL
            {vehicle_filter}
            AND captured_at >= ?
            ORDER BY captured_at ASC
        """
        vehicle_filter = ""
        params: list[object] = [self._cutoff_iso(days)]
        if vehicle_key:
            vehicle_filter = "AND vehicle_key = ?"
            params.insert(0, vehicle_key)

        with self._connect() as conn:
            rows = conn.execute(query.format(vehicle_filter=vehicle_filter), params).fetchall()

        return [
            (datetime.fromisoformat(row["captured_at"]), float(row["battery_percent"]))
            for row in rows
        ]
