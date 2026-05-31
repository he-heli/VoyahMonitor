from __future__ import annotations

import json

import pytest

from voyah_monitor.client import ReadOnlyViolationError, VoyahClient
from voyah_monitor.network_inspector import CapturedRequest, NetworkCapture, classify_request, suggest_allowed_paths
from voyah_monitor.display import format_database_status
from voyah_monitor.scheduling import next_poll_delay_seconds
from voyah_monitor.session import save_session_dict
from voyah_monitor.storage import TelemetryStorage
from voyah_monitor.telemetry import dashboard_items_to_telemetry, normalize_record
from voyah_monitor.vehicle_status import format_dashboard_status
from voyah_monitor.voyah_api import VoyahReadOnlyApi


def _jwt_for_test(exp_offset_seconds: int) -> str:
    import base64
    from datetime import UTC, datetime, timedelta

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "exp": int((datetime.now(UTC) + timedelta(seconds=exp_offset_seconds)).timestamp()),
                "iat": int(datetime.now(UTC).timestamp()),
            }
        ).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def _sample_session_for_test(access_token: str, refresh_token: str) -> dict:
    data = {
        "userId": "69cbbe4daab7077e55b31f4d",
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "userToken": "user-token",
        "widgetId": "widget",
    }
    outer = {
        "authed": True,
        "_persist": {"version": 1, "rehydrated": True},
        "decoded": json.dumps({"_id": data["userId"], "exp": 9999999999}),
        "data": json.dumps(data),
        "selectedOrgId": None,
    }
    return {
        "cookies": [],
        "origins": [
            {
                "origin": "https://app.voyahassist.ru",
                "localStorage": [
                    {"name": "persist:user/auth", "value": json.dumps(outer)},
                ],
            }
        ],
    }


def test_classify_read_get_candidate() -> None:
    result = classify_request("GET", "https://app.voyahassist.ru/api/v1/vehicles", "https://app.voyahassist.ru")
    assert result == "candidate_read_get"


def test_classify_mutation_blocked() -> None:
    result = classify_request("POST", "https://app.voyahassist.ru/api/v1/vehicles/unbind", "https://app.voyahassist.ru")
    assert result == "blocked_mutation"


def test_suggest_allowed_paths() -> None:
    capture = NetworkCapture(
        base_url="https://app.voyahassist.ru",
        captured_at="2026-05-31T00:00:00+00:00",
        requests=[
            CapturedRequest(
                timestamp="t",
                method="GET",
                url="https://app.voyahassist.ru/api/v1/vehicles",
                path="/api/v1/vehicles",
                status=200,
                resource_type="fetch",
                request_content_type=None,
                response_content_type="application/json",
                classification="candidate_read_get",
            ),
            CapturedRequest(
                timestamp="t",
                method="POST",
                url="https://app.voyahassist.ru/api/v1/telemetry",
                path="/api/v1/telemetry",
                status=200,
                resource_type="fetch",
                request_content_type="application/json",
                response_content_type="application/json",
                classification="candidate_read_post",
            ),
        ],
    )
    get_paths, post_paths = suggest_allowed_paths(capture)
    assert get_paths == {"/api/v1/vehicles"}
    assert post_paths == {"/api/v1/telemetry"}


def test_readonly_client_blocks_unknown_get(tmp_path) -> None:
    session_path = tmp_path / "session.json"
    save_session_dict(_sample_session_for_test(_jwt_for_test(600), _jwt_for_test(3600)), session_path)

    from voyah_monitor.config import Settings

    settings = Settings(
        voyah_session_path=session_path,
        voyah_network_capture_path=tmp_path / "capture.json",
        voyah_allowed_get_paths="/api/v1/vehicles",
    )

    client = VoyahClient(settings)
    with pytest.raises(ReadOnlyViolationError):
        client.get_json("/api/v1/unknown")
    client.close()


def test_normalize_record() -> None:
    telemetry = normalize_record(
        {
            "vehicleId": "42",
            "vin": "TESTVIN",
            "odometer": "12345.6",
            "soc": 78,
            "latitude": 55.75,
            "longitude": 37.61,
            "isCharging": True,
        }
    )
    assert telemetry.vehicle_id == "42"
    assert telemetry.odometer_km == 12345.6
    assert telemetry.battery_percent == 78.0
    assert telemetry.is_charging is True


def test_status_shows_all_table_rows(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    storage = TelemetryStorage(db_path)

    first = normalize_record({"_id": "1", "vin": "VIN1", "battery": 70, "lat": 55.1, "lon": 37.1})
    second = normalize_record({"_id": "2", "vin": "VIN2", "odometer": 1000})
    storage.save_snapshot(first)
    storage.save_snapshot(second)

    output = format_database_status(storage.all_snapshots(), storage.all_daily_mileage())
    assert "telemetry_snapshots (2)" in output
    assert "VIN1" in output
    assert "VIN2" in output
    assert "raw_json:" in output
    assert "daily_mileage (1)" in output


def test_voyah_api_blocks_control_paths() -> None:
    with pytest.raises(ReadOnlyViolationError):
        VoyahReadOnlyApi._assert_safe_get_path("/car-service/tbox/69aab8fe2f8bbd597e85ebf2/toggle-location")
    VoyahReadOnlyApi._assert_safe_get_path(
        "/car-service/car/v2/69aab8fe2f8bbd597e85ebf2/driversWithOwner"
    )
    VoyahReadOnlyApi._assert_safe_get_path(
        "/car-service/tbox/69aab8fe2f8bbd597e85ebf2/info"
    )


def test_format_dashboard_status_matches_site_sections() -> None:
    item = {
        "table": {
            "_id": "69aab8fe2f8bbd597e85ebf2",
            "vin": "TESTVIN123",
            "licensePlate": "A123BC",
            "locationStatus": True,
            "lastSensorRequest": "2026-05-31T18:45:00.000Z",
            "carModel": {"displayName": "ФРИ / FREE", "modname": "H97y", "name": "Free"},
            "sensors": {
                "battery": 71,
                "v12": 13,
                "odometer": 1451,
                "remain": 512,
                "lastSensorsRecieved": "2026-05-31T18:45:00.000Z",
            },
        },
        "geo": {"lat": 55.75, "lon": 48.74, "course": 21, "battery": 71},
        "tbox": {
            "isOnline": True,
            "isCentralLockingOn": True,
            "sensors": {
                "chip": {"title": "Доступен"},
                "positionData": {"speed": 0, "lat": 55.75, "lon": 48.74, "course": 21},
                "sensorsData": {
                    "fuelPercentage": 64,
                    "remainsMileageFuel": 224,
                    "batteryPercentage": 71,
                    "remainsMileage": 113,
                    "coolantTemp": 72,
                    "batteryTemp": 24,
                    "12VBatteryVoltage": 12.99,
                    "odometer": 1451,
                    "outsideTemp": 18,
                    "trunkStatus": 0,
                    "centralLockingStatus": 0,
                    "climateFanSpeed": 0,
                },
            },
            "preparation_script": {"running": False},
        },
        "detail": {
            "vin": "TESTVIN123",
            "licensePlate": "A123BC",
            "imsiSim": "9254583477",
            "lastSensorRequest": "2026-05-31T18:45:00.000Z",
            "carModel": {"displayName": "ФРИ / FREE", "modname": "H97y", "color": "Бurgунди"},
            "sensors": {
                "sensorsData": {
                    "fuelPercentage": 64,
                    "remainsMileageFuel": 224,
                    "batteryTemp": 24,
                    "coolantTemp": 72,
                    "outsideTemp": 18,
                    "inBoardTemp": 20,
                }
            },
            "liveSensors": {"soh": 100},
        },
        "drivers": [
            {
                "_id": "1",
                "firstName": "Без имени",
                "lastName": "",
                "phone": "79600311181",
                "kind": "owner",
            }
        ],
        "maintenance": {
            "next": {"label": "Нет данных о предыдущем ТО"},
            "historyTotal": 0,
            "favDealers": [],
            "servicingDealers": [],
            "bookingList": [],
        },
    }
    output = format_dashboard_status([item])
    assert "Таблица (как на сайте)" in output
    assert "Заряд тяговой батареи, %" in output
    assert "Батарея 12V" in output
    assert "Скорость" in output
    assert "Актуальность сенсоров" in output
    assert "Сводка (верх карточки)" in output
    assert "Топливо, %" in output
    assert "Доступен" in output
    assert "Управление (только чтение)" in output
    assert "Об автомобиле" in output
    assert "Климат контроль" in output
    assert "На улице, °C" in output
    assert "Доступы" in output
    assert "+7 (960) 031-11-81" in output
    assert "Техническое обслуживание" in output
    assert "Нет данных о предыдущем ТО" in output
    assert "1451" in output
    assert "SOH, %: 100" in output
    assert "На связи: да" in output
    assert "Широта: 55.75" in output
    assert "Курс: 21" in output
    assert "Передача геопозиции: да" in output


def test_dashboard_items_to_telemetry_extracts_extended_fields() -> None:
    item = {
        "table": {
            "_id": "69aab8fe2f8bbd597e85ebf2",
            "vin": "TESTVIN123",
            "locationStatus": True,
            "carModel": {"displayName": "ФРИ / FREE"},
            "sensors": {"battery": 71, "odometer": 1451, "remain": 113},
        },
        "geo": {"lat": 55.75, "lon": 48.74, "course": 21},
        "detail": {"liveSensors": {"soh": 100}},
        "tbox": {
            "isOnline": True,
            "sensors": {
                "chip": {"title": "Доступен"},
                "positionData": {"lat": 55.75, "lon": 48.74, "course": 21, "speed": 0},
            },
        },
    }
    telemetry = dashboard_items_to_telemetry([item])[0]
    assert telemetry.soh_percent == 100.0
    assert telemetry.is_online is True
    assert telemetry.latitude == 55.75
    assert telemetry.longitude == 48.74
    assert telemetry.course_deg == 21.0
    assert telemetry.location_sharing is True
    assert telemetry.status == "Доступен"


def test_next_poll_delay_seconds_varies_within_jitter() -> None:
    base = 14400
    jitter = 0.25
    delays = [next_poll_delay_seconds(base, jitter) for _ in range(50)]
    assert min(delays) >= base * (1 - jitter)
    assert max(delays) <= base * (1 + jitter)
    assert len(set(delays)) > 1
