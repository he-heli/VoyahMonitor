from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from voyah_monitor.config import Settings
from voyah_monitor.network_inspector import load_network_capture, suggest_allowed_paths
from voyah_monitor.session_manager import SessionManager

MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class ReadOnlyViolationError(RuntimeError):
    """Raised when a request would mutate remote state."""


class VoyahClient:
    """HTTP client that only performs explicitly allowed read operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_manager = SessionManager(settings)
        self._allowed_get = set(settings.allowed_get_paths)
        self._allowed_post = set(settings.allowed_post_paths)
        self._bootstrap_allowed_paths()
        self._client = self.session_manager.build_client()

    def _bootstrap_allowed_paths(self) -> None:
        if self._allowed_get or self._allowed_post:
            return
        capture = load_network_capture(self.settings.voyah_network_capture_path)
        if not capture:
            return
        get_paths, post_paths = suggest_allowed_paths(capture)
        self._allowed_get.update(get_paths)
        self._allowed_post.update(post_paths)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> VoyahClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _normalize_path(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            parsed = urlparse(path)
            if parsed.hostname != urlparse(self.settings.voyah_base_url).hostname:
                raise ReadOnlyViolationError(f"External host is not allowed: {path}")
            return parsed.path
        if not path.startswith("/"):
            return "/" + path
        return path.split("?", 1)[0]

    def _assert_allowed(self, method: str, path: str) -> None:
        upper = method.upper()
        normalized = self._normalize_path(path).lower()

        if any(keyword in normalized for keyword in (
            "delete", "remove", "unbind", "unlink", "update", "edit", "modify",
            "control", "command", "logout", "revoke",
        )):
            raise ReadOnlyViolationError(f"Blocked potentially mutating path: {path}")

        if upper == "GET":
            if normalized not in {p.lower() for p in self._allowed_get}:
                raise ReadOnlyViolationError(
                    f"GET {path} is not in allow-list. "
                    "Run login and configure VOYAH_ALLOWED_GET_PATHS."
                )
            return

        if upper == "POST":
            if normalized not in {p.lower() for p in self._allowed_post}:
                raise ReadOnlyViolationError(
                    f"POST {path} is not in allow-list. "
                    "Only verified read-only POST endpoints are permitted."
                )
            return

        raise ReadOnlyViolationError(f"HTTP method {method} is blocked by read-only policy.")

    def get_json(self, path: str, **kwargs: Any) -> Any:
        self._assert_allowed("GET", path)
        return self.session_manager.request_json(self._client, "GET", path)

    def post_json(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        self._assert_allowed("POST", path)
        return self.session_manager.request_json(
            self._client,
            "POST",
            path,
            json_body=json_body or {},
        )

    def fetch_all_allowed(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in sorted(self._allowed_get):
            try:
                payload = self.get_json(path)
                results.append({"path": path, "method": "GET", "data": payload})
            except Exception as exc:
                results.append({"path": path, "method": "GET", "error": str(exc)})
        for path in sorted(self._allowed_post):
            try:
                payload = self.post_json(path, json_body={})
                results.append({"path": path, "method": "POST", "data": payload})
            except Exception as exc:
                results.append({"path": path, "method": "POST", "error": str(exc)})
        return results


def extract_telemetry_candidates(payload: Any) -> list[dict[str, Any]]:
    """Walk JSON and collect dicts that look like vehicle telemetry records."""
    candidates: list[dict[str, Any]] = []
    telemetry_keys = {
        "odometer", "mileage", "soc", "battery", "latitude", "longitude", "lat", "lon",
        "speed", "vin", "vehicle", "car", "fuel", "range", "temperature",
        "charging", "status", "location",
    }

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            lowered = {str(k).lower(): v for k, v in node.items()}
            if telemetry_keys.intersection(lowered.keys()):
                candidates.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return candidates
