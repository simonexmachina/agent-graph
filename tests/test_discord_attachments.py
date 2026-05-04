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
from unittest.mock import AsyncMock, patch

from agentgraph_connector_discord import refresh_attachment_urls


STORED_JSON = json.dumps([{
    "url": "https://cdn.discordapp.com/attachments/111/222/img.jpg?ex=old&hm=old",
    "filename": "img.jpg",
    "content_type": "image/jpeg",
    "width": 800,
    "height": 600,
}])

FRESH_MESSAGE = {
    "attachments": [{
        "url": "https://cdn.discordapp.com/attachments/111/222/img.jpg?ex=new&hm=new",
        "filename": "img.jpg",
        "content_type": "image/jpeg",
        "width": 800,
        "height": 600,
    }]
}


@pytest.mark.asyncio
async def test_refresh_returns_fresh_url() -> None:
    with patch(
        "agentgraph_connector_discord.load_creds",
        return_value=type("C", (), {"discord": type("D", (), {"bot_token": "tok"})()})(),
    ), patch(
        "agentgraph_connector_discord._api_get",
        new=AsyncMock(return_value=FRESH_MESSAGE),
    ):
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    parsed = json.loads(result)
    assert parsed[0]["url"] == "https://cdn.discordapp.com/attachments/111/222/img.jpg?ex=new&hm=new"


@pytest.mark.asyncio
async def test_refresh_falls_back_on_api_error() -> None:
    with patch(
        "agentgraph_connector_discord.load_creds",
        return_value=type("C", (), {"discord": type("D", (), {"bot_token": "tok"})()})(),
    ), patch(
        "agentgraph_connector_discord._api_get",
        new=AsyncMock(side_effect=Exception("404")),
    ):
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    assert result == STORED_JSON


@pytest.mark.asyncio
async def test_refresh_skips_when_no_credentials() -> None:
    with patch(
        "agentgraph_connector_discord.load_creds",
        return_value=type("C", (), {"discord": None})(),
    ):
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    assert result == STORED_JSON


@pytest.mark.asyncio
async def test_refresh_falls_back_on_creds_exception() -> None:
    with patch(
        "agentgraph_connector_discord.load_creds",
        side_effect=Exception("no creds file"),
    ):
        result = await refresh_attachment_urls("111", "222", STORED_JSON)
    assert result == STORED_JSON
