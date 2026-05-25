"""Connector and auth-provider status formatting shared by CLI and MCP."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from agentgraph.connectors.base import BaseConnector
from agentgraph.core.storage import StorageBackend


def auth_provider_key(connector: BaseConnector) -> str:
    return getattr(connector, "auth_label", None) or connector.source


def auth_provider_connectors(connectors: list[BaseConnector]) -> dict[str, list[BaseConnector]]:
    grouped: dict[str, list[BaseConnector]] = {}
    for connector in connectors:
        grouped.setdefault(auth_provider_key(connector), []).append(connector)
    return grouped


def _list_accounts(connector: BaseConnector) -> list[object]:
    list_accounts = getattr(type(connector), "list_accounts", None)
    if callable(list_accounts):
        return cast(list[object], list_accounts())
    return []


async def _verify_auth(
    connector: BaseConnector,
    account_id: str | None = None,
) -> tuple[str, str | None]:
    verify_auth = type(connector).verify_auth
    try:
        return await verify_auth(account_id)
    except TypeError:
        return await verify_auth()


def _aggregate_auth_status(statuses: list[tuple[str, str | None]]) -> tuple[str, str | None]:
    if any(status == "invalid" for status, _ in statuses):
        return next(item for item in statuses if item[0] == "invalid")
    if any(status == "ok" for status, _ in statuses):
        return ("ok", f"{len(statuses)} account(s)")
    return ("missing", None)


async def auth_provider_status_items(connectors: list[BaseConnector]) -> list[dict[str, object]]:
    """Build JSON-serialisable auth-provider status rows."""
    items: list[dict[str, object]] = []
    for provider, members in auth_provider_connectors(connectors).items():
        representative = members[0]
        accounts = _list_accounts(representative)
        account_rows: list[dict[str, object]] = []
        statuses: list[tuple[str, str | None]] = []
        for account in accounts:
            account_id = getattr(account, "account_id", None)
            status, detail = await _verify_auth(representative, account_id)
            account_rows.append({
                "account_id": getattr(account, "account_id", None),
                "label": getattr(account, "label", None),
                "user_id": getattr(account, "user_id", None),
                "workspace_id": getattr(account, "workspace_id", None),
                "email": getattr(account, "email", None),
                "auth_status": status,
                "auth_detail": detail,
            })
            statuses.append((status, detail))
        auth_status, auth_detail = (
            _aggregate_auth_status(statuses)
            if statuses
            else await _verify_auth(representative)
        )
        connector_sources = [connector.source for connector in members]
        items.append({
            "provider": provider,
            "description": f"Shared auth for {', '.join(connector_sources)}"
            if len(connector_sources) > 1
            else type(representative).auth_description or provider,
            "connectors": connector_sources,
            "shared": len(connector_sources) > 1,
            "auth_status": auth_status,
            "auth_detail": auth_detail,
            "accounts": account_rows,
        })
    return items


async def connector_status_items(
    connectors: list[BaseConnector],
    backend: StorageBackend,
) -> list[dict[str, object]]:
    """Build JSON-serialisable connector status rows."""
    provider_items = await auth_provider_status_items(connectors)
    provider_by_key = {str(item["provider"]): item for item in provider_items}

    poll_delegators: dict[str, list[str]] = {}
    for connector in connectors:
        for delegated_source in type(connector).poll_delegates:
            poll_delegators.setdefault(delegated_source, []).append(connector.source)

    items: list[dict[str, object]] = []
    for connector in connectors:
        provider = auth_provider_key(connector)
        provider_item = provider_by_key[provider]
        interval = connector.poll_interval
        polls = interval is not None
        polled_by = sorted(poll_delegators.get(connector.source, []))
        poll_delegates = list(type(connector).poll_delegates)
        last_synced_at = await backend.get_platform_last_synced_at(connector.source)
        items.append({
            "source": connector.source,
            "description": type(connector).auth_description,
            "auth_provider": provider,
            "shared_auth": bool(provider_item["shared"]),
            "auth_status": provider_item["auth_status"],
            "auth_detail": provider_item["auth_detail"],
            "account_count": len(cast(list[dict[str, object]], provider_item["accounts"])),
            "url_patterns": type(connector).url_patterns,
            "polls": polls,
            "poll_interval_seconds": int(interval.total_seconds()) if interval is not None else None,
            "poll_delegates": poll_delegates,
            "polled_by": polled_by,
            "sync": _sync_label(polls, interval, polled_by, poll_delegates),
            "last_synced_at": last_synced_at.isoformat() if last_synced_at is not None else None,
            "last_sync": _last_sync_label(last_synced_at),
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


def _last_sync_label(last_synced_at: datetime | None) -> str:
    if last_synced_at is None:
        return "never"
    return last_synced_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def _format_interval(seconds: int) -> str:
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return f"{hours}h"
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes}m"
    return f"{seconds}s"
