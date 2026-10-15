from __future__ import annotations

import re
from typing import Any

from voyah_monitor.client import ReadOnlyViolationError
from voyah_monitor.config import Settings
from voyah_monitor.session_manager import SessionManager

MONGO_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")
IMEI_PATTERN = re.compile(r"^\d{10,20}$")

SAFE_POST_PATHS = frozenset(
    {
        "/car-service/car/v2/search",
        "/car-service/car/search-geo",
    }
)

BLOCKED_GET_PATTERNS = (
    re.compile(r"/telemetry-commands"),
    re.compile(r"ownerSuggest"),
    re.compile(r"/owner$"),
    re.compile(r"/drivers(?!WithOwner)"),
    re.compile(r"block_driver"),
    re.compile(r"unblock_driver"),
    re.compile(r"/toggle"),
    re.compile(r"/command"),
    re.compile(r"/check-configuration"),
    re.compile(r"/update-configuration"),
    re.compile(r"/automations/"),
    re.compile(r"/tbox/[a-f0-9]{24}/(?!info$|sensors$|online$)"),
)

ALLOWED_GET_PATTERNS = (
    re.compile(r"^/car-service/car/v2/[a-f0-9]{24}$"),
    re.compile(r"^/car-service/car/v2/[a-f0-9]{24}/driversWithOwner$"),
    re.compile(r"^/car-service/maintenance/[a-f0-9]{24}/overview$"),
    re.compile(r"^/car-service/tbox/[a-f0-9]{24}/info$"),
    re.compile(r"^/car-service/tbox/[a-f0-9]{24}/sensors$"),
    re.compile(r"^/car-service/tbox/[a-f0-9]{24}/online$"),
    # carV2 live card — primary source after VOYAH frontend migration
    re.compile(r"^/client-bff-service/telemetry/\d{10,20}$"),
)


class VoyahReadOnlyApi:
    """Explicit read-only VOYAH API calls used by the web dashboard."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_manager = SessionManager(settings)
        self._client = self.session_manager.build_client()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VoyahReadOnlyApi:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _validate_car_id(car_id: str) -> str:
        if not MONGO_ID_PATTERN.match(car_id):
            raise ReadOnlyViolationError(f"Invalid car id format: {car_id}")
        return car_id

    @staticmethod
    def _validate_imei(imei: str) -> str:
        if not IMEI_PATTERN.match(imei):
            raise ReadOnlyViolationError(f"Invalid IMEI format: {imei}")
        return imei

    @staticmethod
    def _assert_safe_get_path(path: str) -> None:
        if any(pattern.match(path) for pattern in ALLOWED_GET_PATTERNS):
            return
        if any(pattern.search(path) for pattern in BLOCKED_GET_PATTERNS):
            raise ReadOnlyViolationError(f"Blocked read path: {path}")
        raise ReadOnlyViolationError(f"GET {path} is not allowed for status command.")

    @staticmethod
    def _assert_safe_post_path(path: str) -> None:
        if path not in SAFE_POST_PATHS:
            raise ReadOnlyViolationError(f"POST {path} is not allowed for status command.")

    def _get_json(self, path: str) -> Any:
        self._assert_safe_get_path(path)
        return self.session_manager.request_json(self._client, "GET", path)

    def _post_json(self, path: str, body: dict[str, Any]) -> Any:
        self._assert_safe_post_path(path)
        return self.session_manager.request_json(self._client, "POST", path, json_body=body)

    def search_cars(self, *, add_sensors: bool = True, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        return self._post_json(
            "/car-service/car/v2/search",
            {"limit": limit, "offset": offset, "addSensors": add_sensors},
        )

    def search_geo(self) -> dict[str, Any]:
        return self._post_json("/car-service/car/search-geo", {})

    def get_car_by_id(self, car_id: str) -> dict[str, Any]:
        car_id = self._validate_car_id(car_id)
        payload = self._get_json(f"/car-service/car/v2/{car_id}")
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected car detail response.")
        return payload

    def get_car_drivers(self, car_id: str) -> Any:
        car_id = self._validate_car_id(car_id)
        return self._get_json(f"/car-service/car/v2/{car_id}/driversWithOwner")

    def get_maintenance_overview(self, car_id: str) -> dict[str, Any]:
        car_id = self._validate_car_id(car_id)
        payload = self._get_json(f"/car-service/maintenance/{car_id}/overview")
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected maintenance overview response.")
        return payload

    def get_tbox_info(self, car_id: str) -> dict[str, Any]:
        car_id = self._validate_car_id(car_id)
        payload = self._get_json(f"/car-service/tbox/{car_id}/info")
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected tbox info response.")
        return payload

    def get_bff_telemetry(self, imei: str) -> dict[str, Any]:
        imei = self._validate_imei(imei)
        payload = self._get_json(f"/client-bff-service/telemetry/{imei}")
        if not isinstance(payload, dict):
            raise RuntimeError("Unexpected BFF telemetry response.")
        return payload

    @staticmethod
    def normalize_bff_to_tbox(payload: dict[str, Any]) -> dict[str, Any]:
        """Adapt client-bff telemetry into the nested tbox shape formatters expect."""
        raw_sensors = payload.get("sensors") if isinstance(payload.get("sensors"), dict) else {}
        sensors_data: dict[str, Any] = dict(raw_sensors)

        # Formatters treat trunkStatus 0 as closed; BFF sends bool false for closed.
        # Many sensor values arrive as strings ("40", "12.87") — coerce when numeric.
        for key, value in list(sensors_data.items()):
            if isinstance(value, bool) and key.endswith("Status"):
                sensors_data[key] = 1 if value else 0
            elif isinstance(value, str):
                try:
                    sensors_data[key] = float(value) if "." in value else int(value)
                except ValueError:
                    pass

        is_online = payload.get("isOnline")
        if is_online is None:
            is_online = raw_sensors.get("isOnline")
        is_online = bool(is_online)

        def _num(key: str) -> float | None:
            value = raw_sensors.get(key)
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        chip_title = "Доступен" if is_online else "Не подключён"
        online_state = payload.get("onlineState")
        if isinstance(online_state, str) and online_state.lower() == "connected":
            chip_title = "Доступен"

        return {
            "isOnline": is_online,
            "isCentralLockingOn": raw_sensors.get("isCentralLockingOn"),
            "isParked": raw_sensors.get("isParkedOn"),
            "buttons": payload.get("buttons") if isinstance(payload.get("buttons"), list) else [],
            "automations": payload.get("automations") if isinstance(payload.get("automations"), list) else [],
            "warnings": payload.get("warnings") if isinstance(payload.get("warnings"), list) else [],
            "onlineState": online_state,
            "carStateUpdatedAt": payload.get("carStateUpdatedAt"),
            "sensors": {
                "chip": {"title": chip_title},
                "sensorsData": sensors_data,
                "positionData": {
                    "lat": _num("lat"),
                    "lon": _num("lon"),
                    "course": _num("course"),
                    "speed": _num("speed") or 0,
                },
                "lastPing": payload.get("carStateUpdatedAt") or payload.get("positionAt"),
            },
        }

    def fetch_dashboard_status(self) -> list[dict[str, Any]]:
        search = self.search_cars(add_sensors=True)
        geo = self.search_geo()

        cars = search.get("rows", []) if isinstance(search, dict) else []
        geo_rows = geo.get("rows", []) if isinstance(geo, dict) else []
        geo_by_id = {
            row["_id"]: row for row in geo_rows if isinstance(row, dict) and row.get("_id")
        }

        results: list[dict[str, Any]] = []
        for car in cars:
            if not isinstance(car, dict):
                continue
            car_id = car.get("_id")
            if not car_id:
                continue

            item: dict[str, Any] = {
                "table": car,
                "geo": geo_by_id.get(car_id, {}),
            }
            try:
                item["detail"] = self.get_car_by_id(str(car_id))
            except Exception as exc:
                item["detail_error"] = str(exc)
                item["detail"] = {}
            try:
                item["drivers"] = self.get_car_drivers(str(car_id))
            except Exception as exc:
                item["drivers_error"] = str(exc)
            try:
                item["maintenance"] = self.get_maintenance_overview(str(car_id))
            except Exception as exc:
                item["maintenance_error"] = str(exc)

            detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
            imei = detail.get("imei") or car.get("imei")
            tbox: dict[str, Any] | None = None
            if imei:
                try:
                    bff = self.get_bff_telemetry(str(imei))
                    item["bff"] = bff
                    tbox = self.normalize_bff_to_tbox(bff)
                except Exception as exc:
                    item["bff_error"] = str(exc)

            if tbox is None:
                try:
                    tbox = self.get_tbox_info(str(car_id))
                except Exception as exc:
                    item["tbox_error"] = str(exc)
                    tbox = None

            if tbox is not None:
                item["tbox"] = tbox
            results.append(item)

        return results
