from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from voyah_monitor.config import Settings
from voyah_monitor.session import (
    auth_token_from_session,
    cookies_from_session,
    load_session,
    refresh_token_from_session,
    save_session_dict,
    token_expires_at,
    update_auth_tokens,
)

REFRESH_PATH = "/id-service/auth/refresh-token"
REFRESH_SKEW = timedelta(seconds=60)


class SessionExpiredError(RuntimeError):
    """Raised when refresh token is no longer valid and SMS login is required."""


class SessionManager:
    """Keeps access tokens fresh using refreshToken and persists session.json."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.session_path = settings.voyah_session_path
        self.base_url = settings.voyah_base_url
        self.session = load_session(self.session_path)

    def access_token(self) -> str | None:
        return auth_token_from_session(self.session, self.base_url)

    def refresh_token(self) -> str | None:
        return refresh_token_from_session(self.session, self.base_url)

    def access_token_expired(self) -> bool:
        token = self.access_token()
        if not token:
            return True
        expires_at = token_expires_at(token)
        if expires_at is None:
            return True
        return expires_at <= datetime.now(UTC) + REFRESH_SKEW

    def ensure_access_token(self) -> str:
        token = self.access_token()
        if token and not self.access_token_expired():
            return token
        return self.refresh_access_token()

    def refresh_access_token(self) -> str:
        refresh_token = self.refresh_token()
        if not refresh_token:
            raise SessionExpiredError(
                "Refresh token not found in session. Run `voyah-monitor login`."
            )

        response = httpx.post(
            f"{self.base_url}{REFRESH_PATH}",
            json={"refreshToken": refresh_token},
            cookies=cookies_from_session(self.session),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "x-app": "web",
                "User-Agent": "VoyahMonitor/0.1 (read-only)",
            },
            timeout=30.0,
        )

        if response.status_code in {401, 403}:
            raise SessionExpiredError(
                "Refresh token expired or revoked. Run `voyah-monitor login` with SMS."
            )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("accessToken"):
            raise RuntimeError("Unexpected refresh-token response from VOYAH.")

        self.session = update_auth_tokens(self.session, self.base_url, payload)
        save_session_dict(self.session, self.session_path)

        token = auth_token_from_session(self.session, self.base_url)
        if not token:
            raise RuntimeError("Failed to persist refreshed access token.")
        return token

    def build_client(self, *, extra_headers: dict[str, str] | None = None) -> httpx.Client:
        token = self.ensure_access_token()
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": "VoyahMonitor/0.1 (read-only)",
            "x-app": "web",
            "Authorization": f"Bearer {token}",
        }
        if extra_headers:
            headers.update(extra_headers)

        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            cookies=cookies_from_session(self.session),
            timeout=30.0,
            follow_redirects=True,
        )

    def request_json(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        response = client.request(method, path, json=json_body)
        if response.status_code == 401:
            client.headers["Authorization"] = f"Bearer {self.refresh_access_token()}"
            response = client.request(method, path, json=json_body)

        if response.status_code in {401, 403}:
            raise SessionExpiredError(
                "Session is no longer valid. Run `voyah-monitor login` with SMS."
            )

        response.raise_for_status()
        return response.json()
