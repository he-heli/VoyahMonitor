from __future__ import annotations

import pytest

from voyah_monitor.client import ReadOnlyViolationError, VoyahClient
from voyah_monitor.network_inspector import CapturedRequest, NetworkCapture, classify_request, suggest_allowed_paths
from voyah_monitor.telemetry import normalize_record


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


def test_readonly_client_blocks_unknown_get(tmp_path, monkeypatch) -> None:
    session_path = tmp_path / "session.json"
    session_path.write_text('{"cookies": [], "origins": []}', encoding="utf-8")

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
