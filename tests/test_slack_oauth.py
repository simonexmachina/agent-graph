"""Slack OAuth credential and token lifecycle tests."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from agentgraph_connector_slack import _api_get
from agentgraph_connector_slack.auth import (
    OPTIONAL_SCOPES,
    REQUIRED_SCOPES,
    SlackBrowserCredentials,
    SlackOAuthCredentials,
    load_slack_creds,
    refresh_oauth_credentials,
    slack_headers,
    validate_required_scopes,
)

from agentgraph.auth.credentials import load_platform_account, save_platform


@pytest.fixture
def tmp_creds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    credentials_file = tmp_path / "credentials.json"
    monkeypatch.setattr("agentgraph.auth.credentials.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("agentgraph.auth.credentials.CREDENTIALS_FILE", credentials_file)
    return credentials_file


def _oauth_record(*, expires_at: datetime | None = None) -> dict[str, Any]:
    return {
        "auth_method": "oauth",
        "access_token": "xoxe.xoxp-old",
        "refresh_token": "xoxe-refresh-old",
        "expires_at": expires_at or datetime.now(UTC) + timedelta(hours=12),
        "client_id": "123.456",
        "scopes": sorted(REQUIRED_SCOPES | OPTIONAL_SCOPES),
        "user_id": "U1",
        "team_id": "T1",
        "team_name": "Example",
        "account_id": "slack:T1:U1",
    }


def test_legacy_credentials_infer_browser_method(tmp_creds: Path) -> None:
    save_platform("slack", {
        "xoxc_token": "xoxc-T1-old",
        "d_cookie": "cookie",
        "user_id": "U1",
        "team_id": "T1",
    })

    credentials = load_slack_creds()

    assert isinstance(credentials, SlackBrowserCredentials)
    assert credentials.auth_method == "browser"


def test_oauth_credentials_use_discriminator(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record())

    credentials = load_slack_creds()

    assert isinstance(credentials, SlackOAuthCredentials)
    assert credentials.client_id == "123.456"


def test_required_scope_validation_ignores_optional_email() -> None:
    assert validate_required_scopes(sorted(REQUIRED_SCOPES)) == []
    assert validate_required_scopes(sorted(REQUIRED_SCOPES - {"groups:read"})) == [
        "groups:read"
    ]


@pytest.mark.asyncio
async def test_headers_are_bearer_only_for_oauth_and_include_cookie_for_browser(
    tmp_creds: Path,
) -> None:
    save_platform("slack", _oauth_record())
    oauth_headers = await slack_headers()
    save_platform("slack", {"xoxc_token": "xoxc-T1", "d_cookie": "cookie"})
    browser_headers = await slack_headers()

    assert oauth_headers == {
        "Authorization": "Bearer xoxe.xoxp-old",
        "Content-Type": "application/json",
    }
    assert browser_headers["Authorization"] == "Bearer xoxc-T1"
    assert browser_headers["Cookie"] == "d=cookie"


@pytest.mark.asyncio
async def test_proactive_refresh_persists_rotated_tokens(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record(expires_at=datetime.now(UTC) + timedelta(minutes=4)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "ok": True,
            "access_token": "xoxe.xoxp-new",
            "refresh_token": "xoxe-refresh-new",
            "expires_in": 43200,
            "scope": ",".join(sorted(REQUIRED_SCOPES)),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        headers = await slack_headers("slack:T1:U1", client=client)

    stored = load_platform_account("slack", "slack:T1:U1")
    assert headers["Authorization"] == "Bearer xoxe.xoxp-new"
    assert stored is not None
    assert stored["access_token"] == "xoxe.xoxp-new"
    assert stored["refresh_token"] == "xoxe-refresh-new"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_concurrent_refresh_is_coalesced(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record(expires_at=datetime.now(UTC)))
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return httpx.Response(200, json={
            "ok": True,
            "access_token": "new-token",
            "refresh_token": "new-refresh",
            "expires_in": 43200,
            "scope": ",".join(sorted(REQUIRED_SCOPES)),
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        first, second = await asyncio.gather(
            refresh_oauth_credentials("slack:T1:U1", client=client),
            refresh_oauth_credentials("slack:T1:U1", client=client),
        )

    assert first.access_token == second.access_token == "new-token"
    assert calls == 1


@pytest.mark.asyncio
async def test_refresh_failure_keeps_existing_tokens(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record(expires_at=datetime.now(UTC)))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_refresh_token"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RuntimeError, match="invalid_refresh_token"):
            await refresh_oauth_credentials("slack:T1:U1", client=client)

    stored = load_platform_account("slack", "slack:T1:U1")
    assert stored is not None
    assert stored["access_token"] == "xoxe.xoxp-old"


@pytest.mark.asyncio
async def test_api_retries_once_after_token_expired(tmp_creds: Path) -> None:
    save_platform("slack", _oauth_record())
    api_calls = 0
    refresh_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal api_calls, refresh_calls
        if request.url.path.endswith("oauth.v2.user.access"):
            refresh_calls += 1
            return httpx.Response(200, json={
                "ok": True,
                "access_token": "refreshed-token",
                "refresh_token": "refreshed-refresh",
                "expires_in": 43200,
                "scope": ",".join(sorted(REQUIRED_SCOPES)),
            })
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(200, json={"ok": False, "error": "token_expired"})
        assert request.headers["authorization"] == "Bearer refreshed-token"
        return httpx.Response(200, json={"ok": True, "channels": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _api_get(client, "conversations.list", account_id="slack:T1:U1")

    assert result["ok"] is True
    assert api_calls == 2
    assert refresh_calls == 1
