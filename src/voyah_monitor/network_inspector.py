from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Keywords that suggest mutating endpoints — always blocked.
MUTATION_KEYWORDS = (
    "delete",
    "remove",
    "unbind",
    "unlink",
    "detach",
    "update",
    "edit",
    "modify",
    "change",
    "set",
    "create",
    "register",
    "logout",
    "signout",
    "revoke",
    "control",
    "command",
    "lock",
    "unlock",
    "start",
    "stop",
    "activate",
    "deactivate",
)

# Static assets and analytics — not useful for telemetry discovery.
IGNORED_HOST_SUFFIXES = (
    "yandex.ru",
    "yandex.net",
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "smartcaptcha.yandexcloud.net",
)

IGNORED_EXTENSIONS = (
    ".js",
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".woff",
    ".woff2",
    ".ico",
    ".map",
)


@dataclass
class CapturedRequest:
    timestamp: str
    method: str
    url: str
    path: str
    status: int | None
    resource_type: str
    request_content_type: str | None
    response_content_type: str | None
    classification: str
    response_preview: str | None = None


@dataclass
class NetworkCapture:
    base_url: str
    captured_at: str
    requests: list[CapturedRequest] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "captured_at": self.captured_at,
            "requests": [asdict(item) for item in self.requests],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> NetworkCapture:
        requests = [CapturedRequest(**item) for item in payload.get("requests", [])]
        return cls(
            base_url=payload.get("base_url", ""),
            captured_at=payload.get("captured_at", ""),
            requests=requests,
        )


def _looks_like_mutation(path: str, method: str) -> bool:
    normalized = path.lower()
    if method.upper() in {"PUT", "PATCH", "DELETE"}:
        return True
    return any(keyword in normalized for keyword in MUTATION_KEYWORDS)


def _should_ignore(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path.lower()
    host = (parsed.hostname or "").lower()
    if any(host.endswith(suffix) for suffix in IGNORED_HOST_SUFFIXES):
        return True
    if any(path.endswith(ext) for ext in IGNORED_EXTENSIONS):
        return True
    return False


READ_ONLY_POST_SUFFIXES = (
    "/search",
    "/search-geo",
    "/list",
    "/query",
    "/filters",
)


def _is_read_service_path(path: str) -> bool:
    lowered = path.lower()
    if not any(part in lowered for part in ("-service/", "/service/")):
        return False
    if any(keyword in lowered for keyword in MUTATION_KEYWORDS):
        return False
    if any(lowered.endswith(suffix) or suffix in lowered for suffix in READ_ONLY_POST_SUFFIXES):
        return True
    return False


def classify_request(method: str, url: str, base_url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    host = (parsed.hostname or "").lower()
    base_host = urlparse(base_url).hostname or ""

    if _should_ignore(url):
        return "ignored"

    if host and base_host and host != base_host:
        return "external"

    upper_method = method.upper()
    if _looks_like_mutation(path, upper_method):
        return "blocked_mutation"

    if upper_method == "GET":
        if "/api/" in path or path.startswith("/api") or _is_read_service_path(path):
            return "candidate_read_get"
        return "other_get"

    if upper_method == "POST":
        if any(keyword in path.lower() for keyword in ("login", "auth", "captcha", "sms", "code", "sign-up", "sign-in")):
            return "auth"
        if "/api/" in path or path.startswith("/api") or _is_read_service_path(path):
            return "candidate_read_post"
        return "other_post"

    return "other"


def suggest_allowed_paths(capture: NetworkCapture) -> tuple[set[str], set[str]]:
    get_paths: set[str] = set()
    post_paths: set[str] = set()
    for item in capture.requests:
        classification = classify_request(item.method, item.url, capture.base_url)
        if classification == "candidate_read_get":
            get_paths.add(item.path)
        elif classification == "candidate_read_post":
            post_paths.add(item.path)
    return get_paths, post_paths


def save_network_capture(path: Path, capture: NetworkCapture) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(capture.to_dict(), handle, ensure_ascii=False, indent=2)


def load_network_capture(path: Path) -> NetworkCapture | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return NetworkCapture.from_dict(json.load(handle))


def preview_response_body(body: str, limit: int = 500) -> str:
    compact = re.sub(r"\s+", " ", body).strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."
