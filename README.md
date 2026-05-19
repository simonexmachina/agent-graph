# AgentGraph

A local knowledge graph for AI agents. AgentGraph indexes your Slack channels, Discord servers, Google Docs, Sheets, Drive, and Gmail into a searchable graph of entities, people, and relationships — queryable via CLI, web viewer, or MCP server.

## How it works

**The browser extension decides what gets added.** As you browse, the AgentGraph Extension watches which Slack channels, Google Docs, Discord threads, and Gmail conversations you visit. When you dwell on a supported URL for more than 3 seconds, it triggers a fetch. That resource — its content, collaborators, and relationships — is ingested into the local graph.

**Background polling keeps everything current.** Once a resource is in the graph, connectors poll it on a schedule (every few minutes for chat, less frequently for documents) to pick up new messages, replies, and edits without any further browser activity.

```
Browser extension → /observe (focus/blur events)
                         ↓
              Dwell evaluator (3 s threshold)
                         ↓
              Connector (Slack / Discord / Google / Gmail)
                         ↓
          SQLite knowledge graph (local, ~/.agentgraph/)
                   ↙          ↘
         CLI / Web viewer     MCP server → AI agents
```

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Chrome (for the browser extension)

## Quick start

### 1. Install

```bash
uv sync --extra all
```

Or install only the connectors you need:

```bash
uv sync --extra google    # Google Docs, Sheets, Drive, Gmail
uv sync --extra slack     # Slack
uv sync --extra discord   # Discord
```

### 2. Authenticate

Run the interactive setup wizard — it walks through each platform in turn:

```bash
agentgraph onboard
```

Or authenticate platforms individually:

```bash
agentgraph auth google        # Google (Docs, Sheets, Drive, Gmail) via OAuth2
agentgraph auth slack         # Slack cookie credentials
agentgraph auth discord       # Discord bot token
```

**Slack** — cookie-based auth using your browser session. If you are working with an agent that has the `/slack-auth` skill, ask it to run that skill; it extracts the browser token/cookie and saves them for AgentGraph.

Manual fallback:
1. Open Slack in Chrome → DevTools → Network tab
2. Find any request to `slack.com/api/`
3. **Payload** → Form Data → copy the `token` field (starts with `xoxc-`)
4. **Headers** → Request Headers → copy the `d=` value from the `Cookie` header

**Discord** — requires a bot token. Create one at [discord.com/developers/applications](https://discord.com/developers/applications), enable the **Message Content Intent**, and invite the bot to your server with **Read Messages** and **Read Message History** permissions.

**Google** — an OAuth2 browser flow. You'll need a Google Cloud project with the Docs, Drive, Sheets, and Gmail APIs enabled and an OAuth 2.0 client ID configured.

### 3. Start the server

```bash
agentgraph serve
agentgraph serve --reload      # auto-reload on code changes
```

`agentgraph serve` accepts browser dwell events, runs connector pollers, serves the web viewer, and exposes the local HTTP backend at `http://127.0.0.1:8765` by default.

### 4. Install the browser extension

```bash
cd extension
npm install && npm run build
```

Load the unpacked extension in Chrome:
1. Go to `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** and select `extension/dist`

Once installed, browse Slack, Discord, Google Docs, or Gmail normally. AgentGraph will detect your dwell activity and begin indexing.

## Web viewer

Open [http://127.0.0.1:8765/viewer](http://127.0.0.1:8765/viewer) to explore the graph visually. The viewer runs as part of `agentgraph serve` and gives you a manual inspection surface alongside the CLI, MCP server, and browser extension.

## Surfaces

| Surface | Use it for | Entry point |
|---|---|---|
| CLI | Ad hoc search, fetch, ingest, debugging, and operations | `agentgraph search`, `agentgraph fetch`, `agentgraph serve` |
| MCP | Claude Desktop, Claude Code, ChatGPT developer mode, and other MCP clients | `agentgraph mcp-config`, `agentgraph mcp-serve` |
| Browser extension | Passive indexing from supported browser tabs | `extension/dist/` in Chrome Developer Mode |
| Viewer | Visual graph inspection and manual exploration | `http://127.0.0.1:8765/viewer` |

## CLI

```bash
# Search
agentgraph search "project kickoff notes"
agentgraph search "standup" --type Message --limit 5 --platform slack

# Inspect entities
agentgraph get <entity-id>                    # full UUID or 8-char prefix
agentgraph edges <entity-id>
agentgraph edges <entity-id> --type authored --direction in
agentgraph traverse <entity-id> --depth 2

# Filter by type and metadata
agentgraph query --type Message --filter platform=slack --since 12h
agentgraph query --type Document --mine
agentgraph query --type Message --has-attachments --since 7d

# Manually trigger a fetch or poll
agentgraph fetch gdocs <document-id>
agentgraph poll                               # poll all connectors now
agentgraph poll slack                         # poll a single connector
```

`--since` accepts relative durations (`30m`, `12h`, `2d`) or ISO 8601 timestamps.

`--mine` filters to entities with an `authored` edge from the currently authenticated user.

## MCP server

```bash
agentgraph mcp-serve              # stdio transport, for use with Claude Desktop
```

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

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

Available tools: `search_entities`, `get_entity`, `get_edges`, `traverse_graph`, `query_by_filter`, `fetch_entity`, `fetch_entity_by_id`.

## Configuration

Settings are read from environment variables (prefixed `AGENTGRAPH_`) or from `.env` in the config directory. The config directory defaults to `~/.agentgraph` and can be changed with `AGENTGRAPH_CONFIG_DIR`.

| Variable | Default | Description |
|---|---|---|
| `AGENTGRAPH_CONFIG_DIR` | `~/.agentgraph` | Directory for AgentGraph config, credentials, and the default SQLite database |
| `AGENTGRAPH_BACKEND` | `sqlite` | Persistence backend: `sqlite` or `postgres` |
| `AGENTGRAPH_BACKEND_SQLITE_PATH` | `$AGENTGRAPH_CONFIG_DIR/agentgraph.db` | SQLite database path |
| `AGENTGRAPH_DATABASE_URL` | `postgresql://agentgraph:agentgraph@localhost:5432/agentgraph` | PostgreSQL connection URL (only used when backend=`postgres`) |
| `AGENTGRAPH_SERVER_HOST` | `127.0.0.1` | Server bind address |
| `AGENTGRAPH_SERVER_PORT` | `8765` | Server port |
| `AGENTGRAPH_DWELL_THRESHOLD_SECONDS` | `3` | Seconds of focus before triggering a fetch |
| `AGENTGRAPH_RETENTION_DAYS` | `90` | Days before an unvisited entity is garbage collected |
| `AGENTGRAPH_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model for embeddings |
| `AGENTGRAPH_SLACK_WORKSPACE_ID` | _(none)_ | If set, ignore activity from other Slack workspaces |
| `AGENTGRAPH_LOG_LEVEL` | `INFO` | Log level |

### Switching to PostgreSQL

SQLite is the default backend. To switch to PostgreSQL, run:

```bash
agentgraph use-postgres
```

This writes a `docker-compose.yml` to the current directory, saves the backend config to `~/.agentgraph/.env`, and prints next steps. You can supply a custom connection URL with `--url`. To print the compose file to stdout instead of writing it, pass `--compose-out -`.

## Architecture

### Graph schema

- **entities** — messages, documents, channels, threads; includes a 384-dimension content embedding
- **persons** — canonical identities keyed by email
- **edges** — typed relationships: `authored`, `posted_in`, `replied_to`, `mentions`, `references`

### Search

Hybrid search via Reciprocal Rank Fusion (RRF) over:
- **Vector similarity** — cosine distance on `all-MiniLM-L6-v2` embeddings (via sqlite-vec)
- **Full-text** — BM25 trigram search

### Connectors

| Source | Entity types | Fetch trigger |
|---|---|---|
| Slack | Channel, Message | Browser dwell + 5 min polling |
| Discord | Channel, Message | Browser dwell + 5 min polling |
| Google Docs | Document | Browser dwell + 30 min polling |
| Google Sheets | Spreadsheet | Browser dwell + 30 min polling |
| Google Drive | Folder, Document | Browser dwell + 10 min polling |
| Gmail | Thread | Browser dwell + 5 min polling |

**Gmail:** browser dwell indexes any thread you open — inbox, archive, sent, search results, or any label. The background poll sweeps new inbox arrivals and also picks up replies to any thread already in the graph (archived, sent, or otherwise), so no messages in known conversations are missed.

**Google Drive:** polling uses the Drive Changes API to re-fetch any document or spreadsheet already in the graph whenever it is modified. Folders and new files are added via browser dwell.

### Fetch policy

Each connector uses a staleness policy to avoid redundant fetches:

| Decision | Condition | Behaviour |
|---|---|---|
| `FIRST_VISIT` | Never synced | Full fetch |
| `INCREMENTAL` | Last sync > staleness threshold | Fetch changes since last sync |
| `FRESH` | Recently synced | Skip — only update `last_accessed` |

## Development

```bash
uv run pytest                          # unit tests
uv run pytest -m integration           # integration tests (requires running server)
uv run pyright                         # type checking
uv run ruff check agentgraph/          # lint
uv run ruff format agentgraph/         # format
```

### Adding a connector

1. Create a package under `packages/agentgraph-connector-<name>/`
2. Implement `BaseConnector` from `agentgraph.connectors.base`
3. Register it via the `agentgraph.connectors` entry point in `pyproject.toml`
4. Add URL pattern matching to `agentgraph/server/router.py` so the extension can trigger fetches
