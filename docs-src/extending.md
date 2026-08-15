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
- Reuse the same fetch, poll, auth, and graph-upsert model that the built-in Slack, Discord, Google Docs, Drive, Sheets, Gmail, and RSS connectors use.

## Included connectors

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
      <td>Browser observation plus 5 minute polling</td>
    </tr>
    <tr>
      <td>Discord</td>
      <td>Channel, Message</td>
      <td>Bot token</td>
      <td>Browser observation plus 5 minute polling</td>
    </tr>
    <tr>
      <td>Google Docs</td>
      <td>Document</td>
      <td>Google OAuth</td>
      <td>Browser observation plus Drive-backed refresh</td>
    </tr>
    <tr>
      <td>Google Sheets</td>
      <td>Spreadsheet</td>
      <td>Google OAuth</td>
      <td>Browser observation plus Drive-backed refresh</td>
    </tr>
    <tr>
      <td>Google Drive</td>
      <td>Folder, Document</td>
      <td>Google OAuth</td>
      <td>Browser observation for folders and files, plus Drive changes polling</td>
    </tr>
    <tr>
      <td>Gmail</td>
      <td>Email</td>
      <td>Google OAuth</td>
      <td>Browser observation plus background poll and ingest</td>
    </tr>
    <tr>
      <td>RSS</td>
      <td>Folder, Document</td>
      <td>Feed URLs</td>
      <td>Background poll and ingest; validated feed add and OPML import</td>
    </tr>
  </tbody>
</table>

## Connector behavior

- **Browser observation:** supported URLs trigger targeted fetches after the configured observation threshold.
- **Polling:** connectors that support it store cursor state and fetch changes on a schedule.
- **Ingest:** some connectors expose a broader one-shot historical ingest beyond poll behavior.
- **Download metadata:** file-backed entities can expose `metadata.download_url` and `metadata.mime_type` when an agent needs source bytes.

## Connector interface

`BaseConnector` is the author-facing contract for custom integrations. A connector subclass declares its identity and URL ownership, returns graph-shaped batches from `fetch()`, and can optionally participate in auth, background polling, and historical ingest.

## Authoring a connector

A connector is a Python package that subclasses `BaseConnector`, implements the required fetch path, and registers itself through the `agentgraph.connectors` entry point group. This is the extension point you use to teach AgentGraph about your own systems.

### Base contract

The required shape is small: identify which URLs the connector owns, implement `fetch()`, and optionally implement polling, ingest, auth, and user identity hooks. The signatures below match `agentgraph.connectors.base.BaseConnector`.

- `source` is the stable connector identifier used by the CLI, MCP server, and registry.
- `url_patterns` declares static browser URL patterns for observation-based fetches. Connectors can override `observation_url_patterns()` to provide derived patterns.
- `fetch_policy` controls when a targeted fetch should be skipped because a resource is still fresh.
- `can_handle(self, url) -> bool` is required and should confirm whether a specific URL belongs to the connector.
- `resolve_observation_url(self, url)` can asynchronously resolve a browser observation and attach generic fetch metadata to the result.
- `fetch(self, resource_type, resource_id, meta=None, account_id=None) -> EntityBatch` is the required runtime fetch hook.
- `normalise_fetch_id(self, resource_id, entity_type) -> tuple[str, ResourceType]` lets a connector translate stored IDs into fetchable IDs when they differ.
- `poll_interval`, `poll_delegates`, `poll_account_ids()`, `poll()`, and `ingest()` are the optional background refresh hooks.
- `run_auth_flow()`, `list_accounts()`, `get_authenticated_user()`, `verify_auth()`, `current_user_id()`, and `current_user_ids()` are the auth and operator-facing hooks.

The contract is intentionally generic: core AgentGraph code calls these hooks without knowing platform-specific field names or APIs.

### Interface reference

| Member | Required | Purpose |
| --- | --- | --- |
| `source: ClassVar[str]` | Yes | Stable connector key used everywhere the platform is identified. |
| `fetch_policy: ClassVar[FetchPolicy]` | Yes | Declares how long fetched resources stay fresh before an incremental refresh is needed. |
| `url_patterns: ClassVar[list[str]]` | No | URL match patterns that declare which browser URLs this connector can observe. |
| `observation_url_patterns() -> list[str]` | No | Async hook for dynamic browser observation patterns; defaults to `url_patterns`. |
| `can_handle(self, url: str) -> bool` | Yes | Fine-grained URL matcher used after `url_patterns` to decide whether the connector owns a specific URL. |
| `resolve_observation_url(self, url) -> SourceReference \| None` | No | Async browser-observation resolver; may attach fetch metadata while preserving connector-owned URL ownership. |
| `fetch(...) -> EntityBatch` | Yes | Fetch one resource and return the entities, people, and edges needed to represent it in the graph. |
| `normalise_fetch_id(...) -> tuple[str, ResourceType]` | No | Override when stored entity IDs differ from the IDs required by the upstream fetch path. |
| `poll_interval: ClassVar[timedelta \| None]` | No | Enables scheduled background polling when set to a duration. |
| `poll(self, cursor, account_id=None) -> tuple[EntityBatch, dict[str, Any]]` | No | Incremental background refresh hook; return both the batch and the next cursor. |
| `ingest(self, account_id=None) -> EntityBatch` | No | One-shot historical backfill hook for loading data beyond normal polling. |
| `run_auth_flow(cls, account_id=None, add=False) -> None` | No | Interactive auth entry point used by `agentgraph auth` and onboarding flows. |
| `list_accounts(cls) -> list[ConnectorAccount]` | No | Enumerates authenticated accounts when a connector supports multiple identities. |
| `verify_auth(cls, account_id=None) -> tuple[str, str | None]` | No | Reports whether stored credentials are `ok`, `missing`, or `invalid`. |
| `current_user_id(cls) -> str | None` | No | Returns the canonical `Person` identifier for `--mine` filtering. |

`FetchPolicy.decide(last_synced_at)` returns one of three states:

- `FIRST_VISIT`: the resource has never been synced, so do a full fetch.
- `INCREMENTAL`: the resource was synced before but is now stale, so fetch changes since the last sync.
- `FRESH`: the resource was synced recently enough that external fetch work can be skipped.

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
    def run_auth_flow(cls, account_id: str | None = None, add: bool = False) -> None:
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
        account_id: str | None = None,
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

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        # `ingest()` is a one-shot historical backfill. Use it when the
        # connector can fetch more than normal polling covers.
        batch = await _fetch_full_history()
        await upsert_batch(batch)
        return batch

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
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

### Output model

- `EntityRecord` for messages, documents, channels, folders, spreadsheets, and emails.
- `PersonRecord` for authors and participants.
- `EdgeRecord` for authored, posted-in, replied-to, mentions, references, and similar relationships.

### Packaging

Register the connector in `pyproject.toml`.

```toml
[project.entry-points."agentgraph.connectors"]
myplatform = "agentgraph_connector_myplatform:MyConnector"
```
