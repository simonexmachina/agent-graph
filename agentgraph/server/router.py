"""Source router: classifies URLs into source type + resource ID."""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentgraph.config import get_settings
from agentgraph.connectors.base import ResourceType


@dataclass(frozen=True)
class SourceReference:
    source: str
    resource_type: ResourceType
    resource_id: str


# Pattern: https://docs.google.com/document/d/{docId}/...
_GDOCS_RE = re.compile(
    r"https://docs\.google\.com/document/d/(?P<doc_id>[a-zA-Z0-9_-]+)"
)

# Pattern: https://docs.google.com/spreadsheets/d/{spreadsheetId}/...
_GSHEETS_RE = re.compile(
    r"https://docs\.google\.com/spreadsheets/d/(?P<spreadsheet_id>[a-zA-Z0-9_-]+)"
)

# Pattern: https://app.slack.com/client/{workspaceId}/{channelId}
_SLACK_CHANNEL_RE = re.compile(
    r"https://app\.slack\.com/client/(?P<workspace_id>[A-Z0-9]+)/(?P<channel_id>[A-Z0-9]+)"
)

# Pattern: https://discord.com/channels/{guildId}/{channelId}
_DISCORD_CHANNEL_RE = re.compile(
    r"https://discord\.com/channels/(?P<guild_id>\d+)/(?P<channel_id>\d+)"
)

# Pattern: https://discord.com/channels/@me/{channelId}  (DMs and group DMs)
_DISCORD_DM_RE = re.compile(
    r"https://discord\.com/channels/@me/(?P<channel_id>\d+)"
)

# Gmail thread view — extract the ID from the hash fragment.
# Handles: #inbox/{id}, #search/{query}/{id}, #sent/{id}, etc.
# Thread IDs are always 16+ mixed-case/hex chars; Gmail tab labels
# (promotions, social, updates, forums) are short lowercase words and excluded.
_GMAIL_THREAD_RE = re.compile(
    r"https://mail\.google\.com/mail/u/\d+/#[^/\s]+(?:/[^/\s]+)*/(?P<thread_id>[A-Za-z0-9_+=/-]{16,})"
)


def classify_url(url: str) -> SourceReference | None:
    """Return a SourceReference for a known URL, or None if unrecognised."""
    # Sheets must be checked before Docs — both live under docs.google.com
    m = _GSHEETS_RE.match(url)
    if m:
        return SourceReference(
            source="gsheets",
            resource_type="spreadsheet",
            resource_id=m.group("spreadsheet_id"),
        )

    m = _GDOCS_RE.match(url)
    if m:
        return SourceReference(
            source="gdocs",
            resource_type="document",
            resource_id=m.group("doc_id"),
        )

    m = _SLACK_CHANNEL_RE.match(url)
    if m:
        configured = get_settings().slack_workspace_id
        if configured and m.group("workspace_id") != configured:
            return None
        return SourceReference(
            source="slack",
            resource_type="channel",
            resource_id=m.group("channel_id"),
        )

    m = _DISCORD_DM_RE.match(url)
    if m:
        return SourceReference(
            source="discord",
            resource_type="dm",
            resource_id=m.group("channel_id"),
        )

    m = _DISCORD_CHANNEL_RE.match(url)
    if m:
        return SourceReference(
            source="discord",
            resource_type="channel",
            resource_id=m.group("channel_id"),
        )

    m = _GMAIL_THREAD_RE.search(url)
    if m:
        return SourceReference(
            source="gmail",
            resource_type="thread",
            resource_id=m.group("thread_id"),
        )

    return None
