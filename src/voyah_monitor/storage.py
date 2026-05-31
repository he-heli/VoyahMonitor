from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from voyah_monitor.telemetry import VehicleTelemetry


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
                    status TEXT,
                    is_charging INTEGER,
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
                    latitude, longitude, status, is_charging, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    telemetry.status,
                    1 if telemetry.is_charging else 0 if telemetry.is_charging is not None else None,
                    json.dumps(telemetry.raw, ensure_ascii=False),
                ),
            )
            self._update_daily_mileage(conn, key, telemetry)

    def _update_daily_mileage(
        self,
        conn: sqlite3.Connection,
        vehicle_key: str,
        telemetry: VehicleTelemetry,
    ) -> None:
        if telemetry.odometer_km is None:
            return

        day = telemetry.captured_at.astimezone().date().isoformat()
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
                status=row["status"],
                is_charging=bool(row["is_charging"]) if row["is_charging"] is not None else None,
                raw=json.loads(row["raw_json"]),
            )

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
            AND captured_at >= datetime('now', ?)
            ORDER BY captured_at ASC
        """
        vehicle_filter = ""
        params: list[object] = [f"-{days} days"]
        if vehicle_key:
            vehicle_filter = "AND vehicle_key = ?"
            params.insert(0, vehicle_key)

        with self._connect() as conn:
            rows = conn.execute(query.format(vehicle_filter=vehicle_filter), params).fetchall()

        return [
            (datetime.fromisoformat(row["captured_at"]), float(row["battery_percent"]))
            for row in rows
        ]
