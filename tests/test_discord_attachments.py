"""Tests for Discord connector attachment extraction."""

from __future__ import annotations

import json

from agentgraph_connector_discord import _extract_attachments


def _make_attachment(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {
        "url": "https://cdn.discordapp.com/attachments/123/456/photo.jpg",
        "filename": "photo.jpg",
        "content_type": "image/jpeg",
        "width": 1920,
        "height": 1080,
    }
    base.update(kwargs)
    return base


def test_returns_json_string() -> None:
    msg = {"attachments": [_make_attachment()]}
    result = _extract_attachments(msg)
    assert isinstance(result, str)
    parsed = json.loads(result)  # type: ignore[arg-type]
    assert len(parsed) == 1


def test_extracts_url_and_filename() -> None:
    msg = {"attachments": [_make_attachment()]}
    parsed = json.loads(_extract_attachments(msg))  # type: ignore[arg-type]
    assert parsed[0]["url"] == "https://cdn.discordapp.com/attachments/123/456/photo.jpg"
    assert parsed[0]["filename"] == "photo.jpg"


def test_extracts_dimensions_when_present() -> None:
    msg = {"attachments": [_make_attachment()]}
    parsed = json.loads(_extract_attachments(msg))  # type: ignore[arg-type]
    assert parsed[0]["width"] == 1920
    assert parsed[0]["height"] == 1080


def test_omits_dimensions_when_absent() -> None:
    msg = {"attachments": [_make_attachment(width=None, height=None)]}
    parsed = json.loads(_extract_attachments(msg))  # type: ignore[arg-type]
    assert "width" not in parsed[0]
    assert "height" not in parsed[0]


def test_omits_content_type_when_absent() -> None:
    msg = {"attachments": [_make_attachment(content_type="")]}
    parsed = json.loads(_extract_attachments(msg))  # type: ignore[arg-type]
    assert "content_type" not in parsed[0]


def test_skips_attachment_with_no_url() -> None:
    msg = {"attachments": [{"filename": "broken.jpg"}]}
    assert _extract_attachments(msg) is None


def test_empty_attachments_list() -> None:
    assert _extract_attachments({"attachments": []}) is None


def test_no_attachments_key() -> None:
    assert _extract_attachments({}) is None


def test_multiple_attachments() -> None:
    msg = {
        "attachments": [
            _make_attachment(url="https://cdn.discordapp.com/a/1.jpg", filename="1.jpg"),
            _make_attachment(url="https://cdn.discordapp.com/a/2.png", filename="2.png"),
        ]
    }
    parsed = json.loads(_extract_attachments(msg))  # type: ignore[arg-type]
    assert len(parsed) == 2
    assert parsed[0]["url"] == "https://cdn.discordapp.com/a/1.jpg"
    assert parsed[1]["url"] == "https://cdn.discordapp.com/a/2.png"


# ---------------------------------------------------------------------------
# refresh_attachment_urls
# ---------------------------------------------------------------------------

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agentgraph_connector_discord import refresh_attachment_urls

OLD_URL = "https://cdn.discordapp.com/attachments/111/222/img.jpg?ex=old&hm=old"
NEW_URL = "https://cdn.discordapp.com/attachments/111/222/img.jpg?ex=new&hm=new"

STORED_JSON = json.dumps([{
    "url": OLD_URL,
    "filename": "img.jpg",
    "content_type": "image/jpeg",
    "width": 800,
    "height": 600,
}])

REFRESH_RESPONSE = {"refreshed_urls": [{"original": OLD_URL, "refreshed": NEW_URL}]}


def _mock_creds(has_discord: bool = True) -> object:
    discord = type("D", (), {"bot_token": "tok"})() if has_discord else None
    return type("C", (), {"discord": discord})()


def _mock_http_response(data: dict) -> MagicMock:  # type: ignore[type-arg]
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=data)
    return resp


@pytest.mark.asyncio
async def test_refresh_returns_fresh_url() -> None:
    mock_post = AsyncMock(return_value=_mock_http_response(REFRESH_RESPONSE))
    with patch("agentgraph_connector_discord.load_creds", return_value=_mock_creds()), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    parsed = json.loads(result)
    assert parsed[0]["url"] == NEW_URL


@pytest.mark.asyncio
async def test_refresh_preserves_non_url_fields() -> None:
    mock_post = AsyncMock(return_value=_mock_http_response(REFRESH_RESPONSE))
    with patch("agentgraph_connector_discord.load_creds", return_value=_mock_creds()), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    parsed = json.loads(result)
    assert parsed[0]["filename"] == "img.jpg"
    assert parsed[0]["width"] == 800
    assert parsed[0]["height"] == 600


@pytest.mark.asyncio
async def test_refresh_falls_back_on_api_error() -> None:
    mock_post = AsyncMock(side_effect=Exception("503"))
    with patch("agentgraph_connector_discord.load_creds", return_value=_mock_creds()), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    assert result == STORED_JSON


@pytest.mark.asyncio
async def test_refresh_skips_when_no_credentials() -> None:
    with patch("agentgraph_connector_discord.load_creds", return_value=_mock_creds(has_discord=False)):
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    assert result == STORED_JSON


@pytest.mark.asyncio
async def test_refresh_falls_back_on_creds_exception() -> None:
    with patch("agentgraph_connector_discord.load_creds", side_effect=Exception("no creds file")):
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    assert result == STORED_JSON


@pytest.mark.asyncio
async def test_refresh_multiple_attachments() -> None:
    url_a = "https://cdn.discordapp.com/a/1.jpg?ex=old"
    url_b = "https://cdn.discordapp.com/a/2.jpg?ex=old"
    stored = json.dumps([{"url": url_a, "filename": "1.jpg"}, {"url": url_b, "filename": "2.jpg"}])
    response = {"refreshed_urls": [
        {"original": url_a, "refreshed": "https://cdn.discordapp.com/a/1.jpg?ex=new"},
        {"original": url_b, "refreshed": "https://cdn.discordapp.com/a/2.jpg?ex=new"},
    ]}
    mock_post = AsyncMock(return_value=_mock_http_response(response))
    with patch("agentgraph_connector_discord.load_creds", return_value=_mock_creds()), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=MagicMock(post=mock_post))
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        result = await refresh_attachment_urls("111", "222", stored)
    parsed = json.loads(result)
    assert parsed[0]["url"] == "https://cdn.discordapp.com/a/1.jpg?ex=new"
    assert parsed[1]["url"] == "https://cdn.discordapp.com/a/2.jpg?ex=new"
