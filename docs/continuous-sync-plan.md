# Continuous Connector Sync — Plan

## Problem

The graph is currently updated only when the user visits a URL (dwell evaluator) or
manually triggers a fetch. This means content goes stale as soon as the user navigates
away. Messages sent after the last visit, document edits, new threads — none of these
appear until the user revisits.

## Current Architecture

```
browser visit → dwell evaluator → connector.fetch(resource_type, resource_id) → upsert
```

The fetch is purely reactive and scoped to a single resource. There is no background sync.

---

## Per-Platform Sync Strategy

All current connectors use polling. Slack uses cookie auth (which cannot use Socket
Mode or the Events API — both require a bot token), and Discord's Gateway requires
the bot to be a member of channels it receives events for, which we are not doing.

| Connector | Mechanism | Poll interval | Cursor / state | Scope config |
|---|---|---|---|---|
| Slack | `conversations.history` polling per known channel | 5 min | `last_ts` per channel | graph-only (always) |
| Discord | REST message polling per known channel | 5 min | `last_message_id` per channel | graph-only (always) |
| Gmail | `users.history.list` incremental polling | 5 min | `historyId` per account | `gmail_sync_all=true` |
| Google Docs | `drive.changes.list` polling | 10 min | Drive `pageToken` | `drive_sync_all=false` |
| Google Sheets | ↑ shared with Docs | 10 min | ↑ same token | ↑ same setting |

### Slack — `conversations.history` polling

The Slack connector already fetches message history incrementally using the `oldest`
parameter. Background polling generalises this: every 5 minutes, iterate all Slack
Channel entities in the graph and call `conversations.history` for each with
`oldest` set to its last sync time.

Cursor: the existing `synced_at` column on the entity serves as the cursor — no
additional state needed. The connector's existing `fetch()` logic (with
`FetchPolicy.INCREMENTAL`) is reused directly by `poll()`.

### Discord — REST message polling

Same pattern as Slack. Every 5 minutes, iterate all Discord Channel entities and call
`GET /channels/{id}/messages?after={last_message_id}`. The `last_message_id` is
stored per channel in `sync_state` (a snowflake ID, more precise than a timestamp).

### Gmail — `users.history.list` incremental polling

Gmail maintains a server-side `historyId` cursor. Each poll calls
`users.history.list(startHistoryId=last_id)` to get all inbox changes since the last
sync. The response contains only added/modified/deleted message IDs — not full
content. For each changed thread we call `threads.get`.

Cursor stored in `sync_state`: `{"history_id": "1234567"}`.

**Scope configuration: `gmail_sync_all` (default: `true`)**

- `true` — process all threads that appear in the history feed regardless of whether
  they are already in the graph. New threads are ingested automatically as they arrive.
  This is the right default: email is where new context first appears.
- `false` — only re-fetch threads whose IDs are already in the `entities` table.
  Useful if you want the graph to remain scoped strictly to threads you have explicitly
  visited.

An upgrade path exists: Gmail push notifications via Google Cloud Pub/Sub
(`users.watch()`) would give near-real-time delivery, but requires a GCP project and
a public HTTPS endpoint.

### Google Docs / Sheets — Drive Changes API polling

`drive.changes.list(pageToken=...)` returns all changes across My Drive since the
token — **not filtered by file type**. The response includes content edits, renames,
moves, permission changes, deletions, and sharing changes for every file in Drive
(PDFs, images, folders, everything). The file's current state is included in full; the
API does not indicate what specifically changed, only that the file's state has changed.

Both Docs and Sheets share one Drive Changes feed — a single poll covers both
connectors. The SyncEngine runs this poll once, then for each changed file uses
`can_handle(file.webViewLink)` across all registered connectors to find the right
one to dispatch to. This means any new Google connector (Slides, Forms, etc.) is
automatically supported with no changes to the SyncEngine — it just needs a
`can_handle` implementation that matches its Drive URL pattern.

```
for change in drive.changes.list(pageToken=...):
    url = change.file.webViewLink          # e.g. https://docs.google.com/document/d/{id}/edit
    connector = first c in registry where c.can_handle(url)
    if connector:
        dispatch fetch or ingest based on scope config
```

Cursor stored in `sync_state`: `{"page_token": "ABcDeFgH..."}`. One row shared by
`gdocs` and `gsheets` since they use the same Google account and feed. The source key
for this shared cursor is `"drive"`.

**Scope configuration: `drive_sync_all` (default: `false`)**

- `false` — only dispatch changes for `fileId`s already in the `entities` table.
  The graph stays scoped to documents the user has explicitly visited. This is the
  right default: Drive contains far more than documents you care about.
- `true` — dispatch all changes where a registered connector matches `can_handle`,
  regardless of prior graph membership. The graph grows automatically to cover all
  your Docs/Sheets/etc.

---

## API Additions to `BaseConnector`

Two new optional methods. Connectors opt in by overriding them; the default
implementations are no-ops so existing connectors require no changes.

```python
class BaseConnector(ABC):
    # --- Existing ---
    source: ClassVar[str]
    fetch_policy: ClassVar[FetchPolicy]

    # --- New: background polling ---
    poll_interval: ClassVar[timedelta | None] = None
    """Interval between poll() calls. None disables polling for this connector."""

    async def poll(self, cursor: dict[str, Any]) -> tuple[EntityBatch, dict[str, Any]]:
        """Fetch all changes since cursor. Returns (batch, updated_cursor).

        cursor is {} on first call (full sync).
        The SyncEngine persists the cursor between calls; connectors define
        their own cursor schema (e.g. {"history_id": "..."}).
        """
        return EntityBatch(), cursor
```

The cursor dict is opaque to the framework — each connector defines its own keys.
The `SyncEngine` persists it to the `sync_state` table and passes it back unchanged.

---

## Sync State — DB Table

```sql
CREATE TABLE sync_state (
    source     TEXT PRIMARY KEY,   -- matches connector.source, or a shared key
    cursor     JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Cursor examples:
- Slack: not needed — `synced_at` on entities acts as cursor
- Discord: `{"last_message_id": {"C123": "987654321098765432", ...}}` (per channel)
- Gmail: `{"history_id": "1234567"}`
- Drive (Docs + Sheets shared): `{"page_token": "ABcDeFgH..."}`

---

## SyncEngine (`agentgraph/server/sync.py`)

Manages all background sync tasks. Started in `app.py`'s lifespan alongside the
dwell evaluator.

```
startup:
  for each registered connector:
    if poll_interval is set → schedule _poll_connector(connector) via APScheduler

_poll_connector(connector):
  cursor = await load_cursor(connector.source)
  batch, cursor = await connector.poll(cursor)
  await upsert_batch(batch)
  await save_cursor(connector.source, cursor)
```

### Error handling

- Exponential backoff with ±20% jitter: 1s → 2s → 4s → … → 5 min cap
- After 5 consecutive poll failures: log a warning, double the effective interval
  until the next success

---

## Work Breakdown

```
Milestone: Continuous connector sync
│
├── Feature: Sync API on BaseConnector     (poll/cursor protocol + defaults)
├── Feature: sync_state table + SyncEngine (APScheduler wiring, backoff)
│
├── Task: Gmail polling                    (poll_interval=5min, historyId cursor, sync_all=true)
├── Task: Drive Changes polling            (poll_interval=10min, can_handle routing, sync_all=false)
├── Task: Slack polling                    (poll_interval=5min, reuse existing fetch() logic)
└── Task: Discord polling                  (poll_interval=5min, per-channel snowflake cursor)
```

The ordering reflects dependencies: the API and SyncEngine must exist before any
connector can use them. Gmail and Drive are lower-risk starting points (no per-entity
iteration required).
