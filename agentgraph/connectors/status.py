"""Connector status formatting shared by CLI and MCP."""

from __future__ import annotations

from datetime import timedelta

from agentgraph.connectors.base import BaseConnector


def connector_status_items(
    connectors: list[BaseConnector],
    statuses: list[tuple[str, str | None]],
) -> list[dict[str, object]]:
    """Build JSON-serialisable connector status rows."""
    poll_delegators: dict[str, list[str]] = {}
    for connector in connectors:
        for delegated_source in type(connector).poll_delegates:
            poll_delegators.setdefault(delegated_source, []).append(connector.source)

    items: list[dict[str, object]] = []
    for connector, (status, detail) in zip(connectors, statuses, strict=True):
        interval = connector.poll_interval
        polls = interval is not None
        polled_by = sorted(poll_delegators.get(connector.source, []))
        poll_delegates = list(type(connector).poll_delegates)
        items.append({
            "source": connector.source,
            "description": type(connector).auth_description,
            "auth_status": status,
            "auth_detail": detail,
            "url_patterns": type(connector).url_patterns,
            "polls": polls,
            "poll_interval_seconds": int(interval.total_seconds()) if interval is not None else None,
            "poll_delegates": poll_delegates,
            "polled_by": polled_by,
            "sync": _sync_label(polls, interval, polled_by, poll_delegates),
        })
    return items


def _sync_label(
    polls: bool,
    interval: timedelta | None,
    polled_by: list[str],
    poll_delegates: list[str],
) -> str:
    if polls:
        assert interval is not None
        label = f"polling every {_format_interval(int(interval.total_seconds()))}"
        if poll_delegates:
            label = f"{label} for {', '.join(poll_delegates)}"
        return label
    if polled_by:
        return f"via {', '.join(polled_by)} poll"
    return "on-demand"


def _format_interval(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours}h"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes}m"
    return f"{seconds}s"
