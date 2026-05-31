from __future__ import annotations

import re
from typing import Any

from voyah_monitor.client import ReadOnlyViolationError
from voyah_monitor.config import Settings
from voyah_monitor.session_manager import SessionManager

MONGO_ID_PATTERN = re.compile(r"^[a-f0-9]{24}$")

SAFE_POST_PATHS = frozenset(
    {
        "/car-service/car/v2/search",
        "/car-service/car/search-geo",
    }
)

BLOCKED_GET_PATTERNS = (
    re.compile(r"/telemetry-commands"),
    re.compile(r"/client-bff-service/telemetry/"),
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
    re.compile(r"/tbox/[a-f0-9]{24}/(?!info$)"),
)

ALLOWED_GET_PATTERNS = (
    re.compile(r"^/car-service/car/v2/[a-f0-9]{24}$"),
    re.compile(r"^/car-service/car/v2/[a-f0-9]{24}/driversWithOwner$"),
    re.compile(r"^/car-service/maintenance/[a-f0-9]{24}/overview$"),
    re.compile(r"^/car-service/tbox/[a-f0-9]{24}/info$"),
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
            try:
                item["tbox"] = self.get_tbox_info(str(car_id))
            except Exception as exc:
                item["tbox_error"] = str(exc)
            results.append(item)

        return results
