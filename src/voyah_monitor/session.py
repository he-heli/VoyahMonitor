from __future__ import annotations

import json
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
