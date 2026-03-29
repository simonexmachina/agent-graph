"""Tests for the source URL router."""

from __future__ import annotations

import pytest

from agentgraph.server.router import SourceReference, classify_url


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms/edit",
            SourceReference(source="gdocs", resource_type="document", resource_id="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"),
        ),
        (
            "https://docs.google.com/document/d/abc123/view",
            SourceReference(source="gdocs", resource_type="document", resource_id="abc123"),
        ),
        (
            "https://app.slack.com/client/T012AB3CD/C01234567",
            SourceReference(source="slack", resource_type="channel", resource_id="C01234567"),
        ),
        (
            "https://app.slack.com/client/TXXXXXXXX/CYYYYYYY",
            SourceReference(source="slack", resource_type="channel", resource_id="CYYYYYYY"),
        ),
        ("https://github.com/org/repo", None),
        ("https://example.com", None),
        ("not-a-url", None),
    ],
)
def test_classify_url(url: str, expected: SourceReference | None) -> None:
    assert classify_url(url) == expected
