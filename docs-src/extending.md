+++
title = "Extending"
description = "Extend AgentGraph with custom connectors, plus the `BaseConnector` interface and example implementation."
nav_title = "Extending"
section = "Configuration"
order = 30
summary = "AgentGraph can be extended with custom connectors for your own tools and integrations. This page includes the `BaseConnector` interface, hook signatures, and an example implementation."
output = "extending.html"
source_path = "docs-src/extending.md"
aliases = ["connectors.html"]
+++

## Why extend AgentGraph

AgentGraph is designed to be extended with new connectors.

- Build connectors for internal tools, private APIs, or niche SaaS products that are specific to your team.
- Keep your own integration logic outside the core package by shipping it as a separate connector package.
- Reuse the same fetch, poll, auth, and graph-upsert model that the built-in Slack, Discord, Google Docs, Drive, Sheets, and Gmail connectors use.

## Supported connectors

<table>
  <thead>
    <tr>
      <th>Source</th>
      <th>Entities</th>
      <th>Auth</th>
      <th>Refresh model</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Slack</td>
      <td>Channel, Message</td>
      <td>Browser-derived cookie credentials</td>
      <td>Browser dwell plus 5 minute polling</td>
    </tr>
    <tr>
      <td>Discord</td>
      <td>Channel, Message</td>
      <td>Bot token</td>
      <td>Browser dwell plus 5 minute polling</td>
    </tr>
    <tr>
      <td>Google Docs</td>
      <td>Document</td>
      <td>Google OAuth</td>
      <td>Browser dwell plus Drive-backed refresh</td>
    </tr>
    <tr>
      <td>Google Sheets</td>
      <td>Spreadsheet</td>
      <td>Google OAuth</td>
      <td>Browser dwell plus Drive-backed refresh</td>
    </tr>
    <tr>
      <td>Google Drive</td>
      <td>Folder, Document</td>
      <td>Google OAuth</td>
      <td>Browser dwell for folders and files, plus Drive changes polling</td>
    </tr>
    <tr>
      <td>Gmail</td>
      <td>Thread</td>
      <td>Google OAuth</td>
      <td>Browser dwell plus background poll and ingest</td>
    </tr>
  </tbody>
</table>

## Connector behavior

- **Browser dwell:** supported URLs trigger targeted fetches after the configured dwell threshold.
- **Polling:** connectors that support it store cursor state and fetch changes on a schedule.
- **Ingest:** some connectors expose a broader one-shot historical ingest beyond poll behavior.
- **Download metadata:** file-backed entities can expose `metadata.download_url` and `metadata.mime_type` when an agent needs source bytes.

## Connector interface

This is the author-facing reference for implementing a connector against `BaseConnector`.

## Authoring a connector

A connector is a Python package that subclasses `BaseConnector`, implements the required fetch path, and registers itself through the `agentgraph.connectors` entry point group. This is the extension point you use to teach AgentGraph about your own systems.

### Base contract

The required shape is small: identify which URLs the connector owns, implement `fetch()`, and optionally implement polling, ingest, auth, and user identity hooks. The signatures below match `agentgraph.connectors.base.BaseConnector`.

- `source` is the stable connector identifier used by the CLI, MCP server, and registry.
- `url_patterns` declares which browser URLs the connector should claim for dwell-based fetches.
- `fetch_policy` controls when a targeted fetch should be skipped because a resource is still fresh.
- `fetch(self, resource_type, resource_id, meta=None) -> EntityBatch` is the only required runtime method.
- `poll_interval`, `poll()`, and `ingest()` are optional background and backfill hooks.
- `run_auth_flow()`, `get_authenticated_user()`, `verify_auth()`, and `current_user_id()` are the auth and operator-facing hooks.

The contract is intentionally generic: core AgentGraph code calls these hooks without knowing platform-specific field names or APIs.

### Example implementation

This example shows one connector implementing the full contract, including auth, targeted fetch, polling, and historical ingest.

```python
from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx

from agentgraph.connectors.base import (
    BaseConnector,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
    ResourceType,
)
from agentgraph.graph.upsert import upsert_batch


class ExampleConnector(BaseConnector):
    source = "example"
    fetch_policy = FetchPolicy(stale_after_seconds=15 * 60)
    poll_interval: timedelta | None = timedelta(minutes=10)  # type: ignore[assignment]
    url_patterns = ["https://app.example.com/*"]
    auth_label = "example"
    auth_description = "Example platform resources"
    onboard_prompt = "Set up Example?"

    @classmethod
    def run_auth_flow(cls) -> None:
        # Launch the interactive auth flow for `agentgraph auth example`
        # and `agentgraph onboard`.
        from agentgraph_connector_example.auth import run_oauth_flow

        run_oauth_flow()

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        # Return a short operator-facing string for `agentgraph connectors`,
        # or None if credentials are missing.
        from agentgraph_connector_example.auth import load_credentials

        try:
            return load_credentials().email
        except Exception:
            return None

    @classmethod
    async def verify_auth(cls) -> tuple[str, str | None]:
        # Optional but recommended: make a lightweight API call so auth
        # failures show up as "invalid" instead of only "missing".
        from agentgraph_connector_example.auth import load_credentials

        try:
            creds = load_credentials()
        except Exception:
            return ("missing", None)

        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://api.example.com/v1/me",
                headers={"Authorization": f"Bearer {creds.access_token}"},
            )

        if resp.status_code == 200:
            data: dict[str, Any] = resp.json()
            return ("ok", str(data.get("email") or data.get("id")))
        if resp.status_code == 401:
            return ("invalid", "token rejected (401) — run: agentgraph auth example")
        return ("invalid", f"HTTP {resp.status_code}")

    @classmethod
    def current_user_id(cls) -> str | None:
        # Return the canonical identifier stored on the authenticated user's
        # Person entity. This powers `agentgraph query --mine`.
        from agentgraph_connector_example.auth import load_credentials

        try:
            return load_credentials().email
        except Exception:
            return None

    def can_handle(self, url: str) -> bool:
        return "app.example.com" in url

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
    ) -> EntityBatch:
        # `fetch()` is the required connector path. It should return the
        # entities, people, and edges needed to represent one resource.
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            # Nothing changed recently; skip external API work.
            return EntityBatch()

        since = last_sync.isoformat() if last_sync is not None else None
        batch = await _fetch_example_resource(resource_type, resource_id, since=since)
        await upsert_batch(batch)
        return batch

    async def ingest(self) -> EntityBatch:
        # `ingest()` is a one-shot historical backfill. Use it when the
        # connector can fetch more than normal polling covers.
        batch = await _fetch_full_history()
        await upsert_batch(batch)
        return batch

    async def poll(self, cursor: dict[str, Any]) -> tuple[EntityBatch, dict[str, Any]]:
        # `poll()` runs in the background from `agentgraph serve` or
        # `agentgraph poll`. `cursor` is {} on first run; return the next cursor.
        start_cursor = cursor.get("cursor")
        batch, next_cursor = await _fetch_changes_since(start_cursor)
        return batch, {"cursor": next_cursor}


async def _fetch_example_resource(
    resource_type: ResourceType,
    resource_id: str,
    since: str | None,
) -> EntityBatch:
    # Placeholder helper. Real connectors usually call the upstream API,
    # build EntityRecord/PersonRecord/EdgeRecord values, and return them in a batch.
    entity = EntityRecord(
        entity_type="Document",
        platform="example",
        platform_entity_id=resource_id,
        title=f"Example resource {resource_id}",
        metadata={"resource_type": resource_type, "since": since},
    )
    return EntityBatch(entities=[entity], persons=[], edges=[])


async def _fetch_full_history() -> EntityBatch:
    return EntityBatch()


async def _fetch_changes_since(cursor: str | None) -> tuple[EntityBatch, str]:
    return EntityBatch(), cursor or "initial-cursor"
```

### Hook guide

- `fetch(self, resource_type, resource_id, meta=None) -> EntityBatch` is required. This is the targeted fetch path used by browser dwell, `agentgraph fetch`, `fetch_entity`, and stub resolution.
- `poll(self, cursor) -> tuple[EntityBatch, dict[str, Any]]` is optional. Implement it when the upstream system has a changes API, cursor, timestamp, or incremental listing endpoint.
- `ingest(self) -> EntityBatch` is optional. Implement it when you need a one-shot backfill beyond what `poll()` covers, such as "all mail" instead of only new inbox threads.
- `run_auth_flow(cls) -> None` is the interactive setup hook used by `agentgraph auth <source>` and `agentgraph onboard`.
- `get_authenticated_user(cls) -> str | None` returns the short display string shown in `agentgraph connectors`.
- `verify_auth(cls) -> tuple[str, str | None]` is where you should make a live API check if the platform supports a cheap "who am I" endpoint.
- `current_user_id(cls) -> str | None` returns the canonical identifier stored on the user's `Person` entity so `--mine` can work across connectors.

### Output model

- `EntityRecord` for messages, documents, channels, folders, spreadsheets, and threads.
- `PersonRecord` for authors and participants.
- `EdgeRecord` for authored, posted-in, replied-to, mentions, references, and similar relationships.

### Packaging

Register the connector in `pyproject.toml`.

```toml
[project.entry-points."agentgraph.connectors"]
myplatform = "agentgraph_connector_myplatform:MyConnector"
```
