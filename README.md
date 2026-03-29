# AgentGraph

A local knowledge graph for AI agents. AgentGraph watches what you browse, pulls structured data from Slack and Google Docs, and builds a searchable graph of entities, people, and relationships — queryable via CLI or MCP.

## How it works

A Chrome extension observes focus and blur events as you browse. When you dwell on a supported URL (Slack channel, Google Doc) for more than 3 seconds, the backend fetches that resource, extracts entities and relationships, embeds the content, and stores everything in a local PostgreSQL graph. An MCP server exposes the graph to AI agents like Claude.

```
Browser extension → /observe (focus/blur events)
                         ↓
              Dwell evaluator (3s threshold)
                         ↓
              Connector (Slack / Google Docs)
                         ↓
         PostgreSQL + pgvector knowledge graph
                         ↓
              CLI  ·  MCP server  ·  REST API
```

## Requirements

- Python 3.11+
- PostgreSQL 16+ with `pgvector` and `pg_trgm` extensions
- [uv](https://docs.astral.sh/uv/)
- Chrome (for the browser extension)

## Setup

### 1. Database

```bash
docker compose up -d          # starts PostgreSQL with pgvector
```

Or point `AGENTGRAPH_DATABASE_URL` at an existing PostgreSQL instance.

### 2. Install

```bash
uv sync
```

### 3. Authenticate

**Slack** (cookie-based auth):

```bash
agentgraph auth slack
```

**Discord** (bot token auth):

```bash
agentgraph auth discord
```

Create a bot at https://discord.com/developers/applications, enable the **Message Content Intent**, and invite it to your server with `Read Messages` and `Read Message History` permissions.

You'll be prompted for your `xoxc-` token and `d` cookie. To find them:
1. Open Slack in Chrome → DevTools → Network tab
2. Find any request to `slack.com/api/`
3. In the **Payload** tab → Form Data → copy the `token` field (starts with `xoxc-`)
4. In the **Headers** tab → Request Headers → copy the `d=` value from the `Cookie` header

**Google Docs** — choose one of two auth providers:

*Option A: Custom OAuth (default)*
```bash
agentgraph auth google-docs
```
Requires a Google Cloud project with the Docs API and Drive API enabled, and an OAuth 2.0 client ID. Follow the prompts.

*Option B: gcloud Application Default Credentials*
```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/documents.readonly,\
           https://www.googleapis.com/auth/drive.metadata.readonly,\
           https://www.googleapis.com/auth/userinfo.email

export AGENTGRAPH_GOOGLE_AUTH_PROVIDER=gcloud
```

### 4. Start the server

```bash
agentgraph serve
agentgraph serve --reload      # auto-reload on code changes
```

The server listens on `http://127.0.0.1:8765` by default.

### 5. Install the browser extension

```bash
cd extension/horizon-observer
npm install && npm run build
```

Load the unpacked extension from `extension/horizon-observer/dist` in Chrome (`chrome://extensions` → Developer mode → Load unpacked).

## CLI

```bash
agentgraph search "Johnny introduction"
agentgraph search "standup notes" --type Message --limit 5

agentgraph get <entity-id>            # accepts full UUID or 8-char prefix

agentgraph edges <entity-id>
agentgraph edges <entity-id> --type authored --direction in

agentgraph traverse <entity-id> --depth 2

agentgraph query --type Message --filter platform=slack --since 12h
agentgraph query --type Document --mine
agentgraph query --type Message --filter platform=slack --since 1d --order-by created_at
```

### `--since` accepts:
- Relative: `30m`, `12h`, `2d`
- Absolute: ISO 8601 timestamp

### `--mine`
Filters to entities with an `authored` edge from the current authenticated user (resolved from stored credentials).

## MCP server

```bash
agentgraph mcp-serve              # stdio transport, for use with Claude Desktop
```

Add to your Claude Desktop config:

```json
{
  "mcpServers": {
    "agentgraph": {
      "command": "uv",
      "args": ["run", "agentgraph", "mcp-serve"],
      "cwd": "/path/to/agent-graph"
    }
  }
}
```

Available tools: `search_entities`, `get_entity`, `get_edges`, `traverse_graph`, `query_by_filter`.

## Configuration

All settings can be provided as environment variables (prefixed `AGENTGRAPH_`) or in a `.env` file.

| Variable | Default | Description |
|---|---|---|
| `AGENTGRAPH_DATABASE_URL` | `postgresql://agentgraph:agentgraph@localhost:5432/agentgraph` | PostgreSQL connection URL |
| `AGENTGRAPH_SERVER_HOST` | `127.0.0.1` | Server bind address |
| `AGENTGRAPH_SERVER_PORT` | `8765` | Server port |
| `AGENTGRAPH_DWELL_THRESHOLD_SECONDS` | `3` | Seconds of focus before triggering a fetch |
| `AGENTGRAPH_DWELL_POLL_INTERVAL_SECONDS` | `1.0` | How often the dwell evaluator runs |
| `AGENTGRAPH_RETENTION_DAYS` | `90` | Days before an unvisited entity is garbage collected |
| `AGENTGRAPH_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model for embeddings |
| `AGENTGRAPH_SLACK_WORKSPACE_ID` | _(none)_ | If set, ignore observations from other Slack workspaces |
| `AGENTGRAPH_GOOGLE_AUTH_PROVIDER` | `oauth` | `oauth` or `gcloud` |
| `AGENTGRAPH_LOG_LEVEL` | `INFO` | Log level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

## Architecture

### Graph schema

- **persons** — canonical identities keyed by email
- **platform_identities** — links a person to a platform-specific user ID (Slack user, Google account)
- **entities** — messages, documents, channels; includes a 384-dimension content embedding
- **edges** — typed relationships: `authored`, `posted_in`, `replied_to`, `mentions`, `collaborated`, `references`
- **observations** — raw focus/blur events from the browser extension

### Search

Hybrid search using Reciprocal Rank Fusion (RRF) over:
- **Vector similarity** — pgvector cosine distance on `all-MiniLM-L6-v2` embeddings
- **Full-text** — PostgreSQL `tsvector` with `english` dictionary

### Connectors

| Source | Trigger | What's fetched |
|---|---|---|
| Slack | Dwell on `app.slack.com/client/…` | Channel messages, thread replies, user profiles, `authored` / `posted_in` / `replied_to` / `mentions` edges |
| Google Docs | Dwell on `docs.google.com/document/…` | Document content, collaborators, document owners (`authored` edge) |
| Discord | Dwell on `discord.com/channels/…` | Channel messages, thread replies, user profiles, `authored` / `posted_in` / `replied_to` / `mentions` edges |

### Fetch policy

| Policy | Condition | Behaviour |
|---|---|---|
| `FIRST_VISIT` | Never synced | Full fetch, no time filter |
| `INCREMENTAL` | Synced > 5 min ago | Fetch since last sync |
| `FRESH` | Synced ≤ 5 min ago | Skip |

### Authorship

`authored` edges are used for both Slack messages (posted by a user) and Google Docs (owned by a user via the Drive API). The `--mine` flag on `agentgraph query` and the `authored_by_me` parameter on the MCP `query_by_filter` tool filter results to entities with an `authored` edge from the currently authenticated user.

## Development

```bash
uv run pytest                          # unit tests only
uv run pytest -m integration           # include integration tests (requires DB)
uv run pyright                         # type checking
uv run ruff check agentgraph/          # lint
uv run ruff format agentgraph/         # format
```
