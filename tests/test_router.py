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
            "https://drive.google.com/file/d/19ccFHOXCcr4s62HJb3Eih3JqAd2xIZDq/view",
            SourceReference(source="gdrive", resource_type="document", resource_id="19ccFHOXCcr4s62HJb3Eih3JqAd2xIZDq"),
        ),
        (
            "https://app.slack.com/client/T012AB3CD/C01234567",
            SourceReference(source="slack", resource_type="channel", resource_id="T012AB3CD/C01234567"),
        ),
        (
            "https://app.slack.com/client/TXXXXXXXX/CYYYYYYY",
            SourceReference(source="slack", resource_type="channel", resource_id="TXXXXXXXX/CYYYYYYY"),
        ),
        (
            "https://mail.google.com/mail/u/0/#inbox/18f0c1d2e3a4b5c6",
            SourceReference(source="gmail", resource_type="thread", resource_id="18f0c1d2e3a4b5c6"),
        ),
        (
            "https://mail.google.com/mail/u/0/#all/thread-a:r-2822072678036458979|msg-f:1829022956460283525",
            SourceReference(
                source="gmail",
                resource_type="thread",
                resource_id="thread-a:r-2822072678036458979|msg-f:1829022956460283525",
            ),
        ),
        ("https://github.com/org/repo", None),
        ("https://example.com", None),
        ("not-a-url", None),
    ],
)
def test_classify_url(url: str, expected: SourceReference | None) -> None:
    assert classify_url(url) == expected
