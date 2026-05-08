---
# agent-graph-ymtv
title: Agent query panel with session-tracked node highlighting
status: draft
type: feature
priority: normal
created_at: 2026-05-04T13:54:43Z
updated_at: 2026-05-04T13:57:53Z
---

Add a query panel to the graph viewer that sends prompts to a Claude Code agent running in the project directory (with access to the /graph skill), streams the response back via SSE, and highlights the graph nodes the agent accessed during the query using session ID tracking.

## Plan

### Overview

The feature has four layers that each need changing:

1. **Config** — new settings for the agent harness
2. **Session tracker** — in-memory store mapping session IDs to accessed entity IDs
3. **CLI transport** — thread session ID from env var through to server as a request header
4. **Server** — CLI API records accesses; new agent endpoint spawns the harness and streams results
5. **Viewer** — query panel UI that streams the response and highlights accessed nodes

---

### 1. `agentgraph/config.py`

Add two new fields to `Settings`:

- `agent_harness_command: str` — command to invoke (default `"claude"`)
- `agent_harness_cwd: str` — working directory for the subprocess (default `"."`)

---

### 2. `agentgraph/server/session.py` (new file)

A lightweight in-memory session tracker:

```python
class SessionTracker:
    def create(self, session_id: str) -> None
    def record(self, session_id: str, entity_ids: Iterable[str]) -> None
    def get(self, session_id: str) -> list[str]   # deduplicated, insertion-ordered
    def close(self, session_id: str) -> None

tracker: SessionTracker  # module-level singleton
```

`record()` is a no-op for unknown session IDs so the CLI can always send the header without the server needing an open session.

---

### 3. `agentgraph/cli_query.py`

Thread session ID through `_get()` and `_post()`:

- Read `os.environ.get("AGENTGRAPH_SESSION_ID")` at call time
- When set, add header `X-Agentgraph-Session: <id>` to the httpx request

No changes to CLI commands — the env var is invisible to the user.

---

### 4. `agentgraph/server/cli_api.py`

Add a `_record_session` helper that reads the `X-Agentgraph-Session` header (optional FastAPI `Header` dependency) and calls `tracker.record()` when present.

Apply to every endpoint that returns entity data and record the entity IDs from the response:

| Endpoint | IDs to record |
|---|---|
| `/search` | all IDs in result list |
| `/entity/{id}` | the single returned ID |
| `/edges/{id}` | the queried entity's ID |
| `/traverse/{id}` | all node IDs in result |
| `/browse` | all node IDs in result |
| `/query` | all IDs in result list |

Endpoints remain fully backwards-compatible — the header is always optional.

---

### 5. `agentgraph/server/agent_api.py` (new file)

New FastAPI router at `/agent`.

#### `POST /agent/query`

Request body: `{ "query": str }`  
Response: `text/event-stream`

Two SSE event types:

| Event | Payload | When |
|---|---|---|
| `text` | stdout chunk | streaming, as produced |
| `nodes` | JSON array of entity ID strings | single event after process exits |
| `error` | tail of stderr | only on non-zero exit |

Implementation:

1. Generate `session_id = str(uuid4())`
2. `tracker.create(session_id)`
3. Resolve `agent_harness_cwd` (expand `~`, resolve relative to server cwd)
4. Spawn: `asyncio.create_subprocess_exec(*shlex.split(command), "-p", query, cwd=cwd, env={**os.environ, "AGENTGRAPH_SESSION_ID": session_id}, stdout=PIPE, stderr=PIPE)`
5. Stream stdout as `event: text` chunks
6. On exit: emit `event: nodes` with `tracker.get(session_id)`
7. `tracker.close(session_id)`

Mount router in `agentgraph/server/app.py`.

---

### 6. `agentgraph/server/static/viewer.html`

Add a query panel at the bottom of the existing sidebar.

**Elements:**
- `<textarea id="agent-query-input">` — prompt input
- `<button id="agent-query-send">` — disabled while a query is running
- `<div id="agent-response">` — scrollable, appends chunks as they arrive

**Behaviour:**

```js
// POST + ReadableStream (not EventSource — that's GET-only)
async function sendQuery(query) {
    const resp = await fetch('/agent/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
    });
    // parse SSE frames from resp.body reader
    // 'text' event → append to #agent-response
    // 'nodes' event → parse JSON, highlight cy nodes
}
```

Node highlighting: on the `nodes` event, call `cy.getElementById(id).addClass('queried')` for each ID. Add a `queried` Cytoscape style class (e.g. accent border/fill). Clear previous highlights when a new query starts.

---

### 7. Tests

- **Unit — `tests/test_session.py`**: create/record/get/close; record on unknown session is no-op; deduplication preserves insertion order
- **Unit — `tests/test_cli_query.py`**: `_get`/`_post` include `X-Agentgraph-Session` header when env var is set, omit otherwise
- **Integration — `tests/test_agent_api.py`**: mock subprocess; verify SSE stream emits `text` events then a `nodes` event; verify session cleaned up after query
