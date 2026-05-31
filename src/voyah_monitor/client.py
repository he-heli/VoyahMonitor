from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from voyah_monitor.config import Settings
from voyah_monitor.network_inspector import load_network_capture, suggest_allowed_paths
from voyah_monitor.session import cookies_from_session, load_session, local_storage_from_session

MUTATION_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class ReadOnlyViolationError(RuntimeError):
    """Raised when a request would mutate remote state."""


class VoyahClient:
    """HTTP client that only performs explicitly allowed read operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session = load_session(settings.voyah_session_path)
        self._allowed_get = set(settings.allowed_get_paths)
        self._allowed_post = set(settings.allowed_post_paths)
        self._bootstrap_allowed_paths()

        headers = self._build_headers()
        self._client = httpx.Client(
            base_url=settings.voyah_base_url,
            headers=headers,
            cookies=cookies_from_session(self.session),
            timeout=30.0,
            follow_redirects=True,
        )

    def _bootstrap_allowed_paths(self) -> None:
        if self._allowed_get or self._allowed_post:
            return
        capture = load_network_capture(self.settings.voyah_network_capture_path)
        if not capture:
            return
        get_paths, post_paths = suggest_allowed_paths(capture)
        self._allowed_get.update(get_paths)
        self._allowed_post.update(post_paths)

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "VoyahMonitor/0.1 (read-only)",
        }
        storage = local_storage_from_session(self.session, self.settings.voyah_base_url)
        for key in ("token", "accessToken", "access_token", "authToken", "authorization"):
            if key in storage:
                value = storage[key]
                if key.lower() == "authorization" or value.lower().startswith("bearer "):
                    headers["Authorization"] = value
                else:
                    headers["Authorization"] = f"Bearer {value}"
                break
        return headers

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
        response = self._client.get(path, **kwargs)
        response.raise_for_status()
        return response.json()

    def post_json(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        self._assert_allowed("POST", path)
        response = self._client.post(path, json=json_body, **kwargs)
        response.raise_for_status()
        return response.json()

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
        "odometer", "mileage", "soc", "battery", "latitude", "longitude",
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
