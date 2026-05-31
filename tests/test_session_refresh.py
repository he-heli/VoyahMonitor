from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from voyah_monitor.config import Settings
from voyah_monitor.session import (
    auth_token_from_session,
    load_session,
    refresh_token_from_session,
    save_session_dict,
    token_expires_at,
    update_auth_tokens,
)
from voyah_monitor.session_manager import SessionExpiredError, SessionManager


def _sample_session(access_token: str, refresh_token: str) -> dict:
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


def _jwt(exp_offset_seconds: int) -> str:
    import base64

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


def test_update_auth_tokens_persists_new_access_token() -> None:
    session = _sample_session("old-access", "old-refresh")
    updated = update_auth_tokens(
        session,
        "https://app.voyahassist.ru",
        {
            "userId": "69cbbe4daab7077e55b31f4d",
            "accessToken": "new-access",
            "refreshToken": "new-refresh",
            "userToken": "new-user",
            "widgetId": "widget-2",
        },
    )
    assert auth_token_from_session(updated, "https://app.voyahassist.ru") == "new-access"
    assert refresh_token_from_session(updated, "https://app.voyahassist.ru") == "new-refresh"


def test_session_manager_refreshes_expired_access_token(tmp_path, monkeypatch) -> None:
    expired_access = _jwt(-120)
    valid_refresh = _jwt(3600 * 24 * 30)
    session_path = tmp_path / "session.json"
    save_session_dict(_sample_session(expired_access, valid_refresh), session_path)

    settings = Settings(
        voyah_session_path=session_path,
        voyah_base_url="https://app.voyahassist.ru",
    )

    new_access = _jwt(600)

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        assert url.endswith("/id-service/auth/refresh-token")
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={
                "userId": "69cbbe4daab7077e55b31f4d",
                "accessToken": new_access,
                "refreshToken": valid_refresh,
                "userToken": "user-token-2",
                "widgetId": "widget",
            },
            request=request,
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    manager = SessionManager(settings)
    token = manager.ensure_access_token()
    assert token == new_access

    reloaded = load_session(session_path)
    assert auth_token_from_session(reloaded, settings.voyah_base_url) == new_access


def test_session_manager_raises_when_refresh_revoked(tmp_path, monkeypatch) -> None:
    session_path = tmp_path / "session.json"
    save_session_dict(_sample_session(_jwt(-120), _jwt(3600)), session_path)
    settings = Settings(voyah_session_path=session_path, voyah_base_url="https://app.voyahassist.ru")

    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, **kwargs: httpx.Response(
            401,
            json={"message": "jwt expired"},
            request=httpx.Request("POST", url),
        ),
    )

    manager = SessionManager(settings)
    with pytest.raises(SessionExpiredError):
        manager.refresh_access_token()
