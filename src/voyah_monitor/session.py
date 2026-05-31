from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext


async def save_session(context: BrowserContext, path: Path) -> None:
    """Persist Playwright storage state (cookies + localStorage)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    await context.storage_state(path=str(path))


def load_session(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Session file not found: {path}. Run `voyah-monitor login` first."
        )
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def session_exists(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def cookies_from_session(session: dict[str, Any]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for item in session.get("cookies", []):
        name = item.get("name")
        value = item.get("value")
        if name and value is not None:
            cookies[name] = value
    return cookies


def local_storage_from_session(session: dict[str, Any], origin: str | None = None) -> dict[str, str]:
    storage: dict[str, str] = {}
    for entry in session.get("origins", []):
        if origin and entry.get("origin") != origin:
            continue
        for item in entry.get("localStorage", []):
            name = item.get("name")
            value = item.get("value")
            if name and value is not None:
                storage[name] = value
    return storage


def save_session_dict(session: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(session, handle, ensure_ascii=False, indent=2)


def _parse_persist_auth(storage: dict[str, str]) -> dict[str, Any] | None:
    persist_auth = storage.get("persist:user/auth")
    if not persist_auth:
        return None
    try:
        return json.loads(persist_auth)
    except json.JSONDecodeError:
        return None


def auth_data_from_session(session: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    storage = local_storage_from_session(session, base_url)
    outer = _parse_persist_auth(storage)
    if not outer:
        return None

    data_raw = outer.get("data")
    if isinstance(data_raw, str):
        try:
            data = json.loads(data_raw)
        except json.JSONDecodeError:
            return None
    elif isinstance(data_raw, dict):
        data = data_raw
    else:
        return None

    return data if isinstance(data, dict) else None


def refresh_token_from_session(session: dict[str, Any], base_url: str) -> str | None:
    data = auth_data_from_session(session, base_url)
    if not data:
        return None
    token = data.get("refreshToken")
    return str(token) if token else None


def token_expires_at(token: str) -> datetime | None:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        exp = claims.get("exp")
        if exp is None:
            return None
        return datetime.fromtimestamp(int(exp), UTC)
    except (IndexError, ValueError, TypeError, json.JSONDecodeError):
        return None


def update_auth_tokens(
    session: dict[str, Any],
    base_url: str,
    tokens: dict[str, Any],
) -> dict[str, Any]:
    """Merge refreshed tokens into Playwright storage state."""
    for entry in session.get("origins", []):
        if entry.get("origin") != base_url:
            continue

        for item in entry.get("localStorage", []):
            if item.get("name") != "persist:user/auth":
                continue

            outer = json.loads(item["value"])
            data_raw = outer.get("data")
            if isinstance(data_raw, str):
                data = json.loads(data_raw)
            elif isinstance(data_raw, dict):
                data = dict(data_raw)
            else:
                data = {}

            for key in ("userId", "accessToken", "refreshToken", "userToken", "widgetId"):
                if key in tokens and tokens[key] is not None:
                    data[key] = tokens[key]

            outer["data"] = json.dumps(data, ensure_ascii=False)
            outer["authed"] = True

            access_token = data.get("accessToken")
            if isinstance(access_token, str):
                expires_at = token_expires_at(access_token)
                if expires_at is not None:
                    outer["decoded"] = json.dumps(
                        {"_id": data.get("userId"), "exp": int(expires_at.timestamp())},
                        ensure_ascii=False,
                    )

            item["value"] = json.dumps(outer, ensure_ascii=False)
            return session

    raise RuntimeError("persist:user/auth entry not found in session state.")


def auth_token_from_session(session: dict[str, Any], base_url: str) -> str | None:
    """Extract Bearer access token from Playwright storage state."""
    storage = local_storage_from_session(session, base_url)

    for key in ("token", "accessToken", "access_token", "authToken", "authorization"):
        if key in storage:
            value = storage[key]
            if key.lower() == "authorization" or value.lower().startswith("bearer "):
                return value.removeprefix("Bearer ").strip()
            return value

    persist_auth = storage.get("persist:user/auth")
    if persist_auth:
        data = auth_data_from_session(session, base_url)
        if data:
            token = data.get("accessToken")
            return str(token) if token else None

    return None
