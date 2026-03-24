"""Source router: classifies URLs into source type + resource ID."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceReference:
    source: str           # 'gdocs' | 'slack'
    resource_type: str    # 'document' | 'channel'
    resource_id: str


# Pattern: https://docs.google.com/document/d/{docId}/...
_GDOCS_RE = re.compile(
    r"https://docs\.google\.com/document/d/(?P<doc_id>[a-zA-Z0-9_-]+)"
)

# Pattern: https://app.slack.com/client/{workspaceId}/{channelId}
_SLACK_CHANNEL_RE = re.compile(
    r"https://app\.slack\.com/client/(?P<workspace_id>[A-Z0-9]+)/(?P<channel_id>[A-Z0-9]+)"
)


def classify_url(url: str) -> SourceReference | None:
    """Return a SourceReference for a known URL, or None if unrecognised."""
    m = _GDOCS_RE.match(url)
    if m:
        return SourceReference(
            source="gdocs",
            resource_type="document",
            resource_id=m.group("doc_id"),
        )

    m = _SLACK_CHANNEL_RE.match(url)
    if m:
        return SourceReference(
            source="slack",
            resource_type="channel",
            resource_id=m.group("channel_id"),
        )

    return None
