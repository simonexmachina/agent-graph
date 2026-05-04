"""Tests for Discord connector attachment extraction."""

from __future__ import annotations

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


def test_extracts_url_and_filename() -> None:
    msg = {"attachments": [_make_attachment()]}
    result = _extract_attachments(msg)
    assert len(result) == 1
    assert result[0]["url"] == "https://cdn.discordapp.com/attachments/123/456/photo.jpg"
    assert result[0]["filename"] == "photo.jpg"


def test_extracts_dimensions_when_present() -> None:
    msg = {"attachments": [_make_attachment()]}
    result = _extract_attachments(msg)
    assert result[0]["width"] == 1920
    assert result[0]["height"] == 1080


def test_omits_dimensions_when_absent() -> None:
    msg = {"attachments": [_make_attachment(width=None, height=None)]}
    result = _extract_attachments(msg)
    assert "width" not in result[0]
    assert "height" not in result[0]


def test_omits_content_type_when_absent() -> None:
    msg = {"attachments": [_make_attachment(content_type="")]}
    result = _extract_attachments(msg)
    assert "content_type" not in result[0]


def test_skips_attachment_with_no_url() -> None:
    msg = {"attachments": [{"filename": "broken.jpg"}]}
    result = _extract_attachments(msg)
    assert result == []


def test_empty_attachments_list() -> None:
    assert _extract_attachments({"attachments": []}) == []


def test_no_attachments_key() -> None:
    assert _extract_attachments({}) == []


def test_multiple_attachments() -> None:
    msg = {
        "attachments": [
            _make_attachment(url="https://cdn.discordapp.com/a/1.jpg", filename="1.jpg"),
            _make_attachment(url="https://cdn.discordapp.com/a/2.png", filename="2.png"),
        ]
    }
    result = _extract_attachments(msg)
    assert len(result) == 2
    assert result[0]["url"] == "https://cdn.discordapp.com/a/1.jpg"
    assert result[1]["url"] == "https://cdn.discordapp.com/a/2.png"
