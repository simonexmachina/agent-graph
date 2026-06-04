# AgentGraph

AgentGraph is a local knowledge graph for AI agents. It indexes content from Slack, Discord, Gmail, Google Docs, Google Sheets, and Google Drive into a queryable graph of entities, people, and relationships that you can use from the CLI, web viewer, browser extension, or MCP.

## Docs

- [Install](docs-src/install.md)
- [Quickstart](docs-src/quickstart.md)
- [Configuration](docs-src/configuration.md)
- [Extending](docs-src/extending.md)
- [Commands](docs-src/commands/index.md)
- [MCP tools](docs-src/mcp/index.md)
- [Privacy](docs-src/privacy.md)

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Chrome for the browser extension

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Clone and sync

```bash
git clone https://github.com/simonexmachina/agent-graph
cd agent-graph
uv sync --extra all
```

Or install only the connectors you need:

```bash
uv sync --extra google
uv sync --extra slack
uv sync --extra discord
```

Credentials and local state live in `~/.agentgraph/` by default, or under `AGENTGRAPH_CONFIG_DIR` if you set a custom config directory.

## Quick Start

### 1. Authenticate connectors

Run the guided onboarding flow:

```bash
agentgraph onboard
```

Or authenticate a single source directly:

```bash
agentgraph auth <source>
```

### 2. Start AgentGraph

```bash
agentgraph serve
```

The default server URL is `http://127.0.0.1:8765`.

### 3. Install the browser extension

Install the [AgentGraph Chrome Extension](https://chromewebstore.google.com/detail/agentgraph-extension/iilkfclglabllelhjacijldknapbhidi?authuser=0&hl=en-AU) from the Chrome Web Store.

To build it locally instead:

```bash
cd extension
npm install
npm run build
```

Then open `chrome://extensions`, enable Developer Mode, click **Load unpacked**, and select `extension/dist/`.

### 4. Browse something supported

Open a Slack channel, Discord thread, Google Doc, Google Sheet, Gmail thread, or Drive folder and keep the tab focused long enough for the dwell threshold to trigger a fetch.

### 5. Verify entities landed

```bash
agentgraph connectors --json
agentgraph search "slack" --limit 5
agentgraph query --type Document --limit 5
```

### 6. Connect an assistant

```bash
agentgraph mcp-config
```

Use the printed config with Claude Desktop or Claude Code, or expose SSE / streaming HTTP for ChatGPT developer mode.

## How It Works

The browser extension watches supported URLs and sends dwell events to your local AgentGraph server. When you stay on a page long enough, the matching connector fetches the resource and turns it into graph entities, people, and edges. After that first fetch, supported connectors keep known resources fresh with background polling.

```text
Browser extension -> local server -> connector -> local graph
                                         |
                                         +-> CLI / viewer / MCP
```

AgentGraph is local-first. Indexed content is stored in a local SQLite database. The project does not run a hosted service for your graph data.

## Surfaces

| Surface | Use it for | Entry point |
| --- | --- | --- |
| CLI | Search, fetch, ingest, debugging, and operations | `agentgraph search`, `agentgraph fetch`, `agentgraph serve` |
| MCP | Claude Desktop, Claude Code, ChatGPT developer mode, and other MCP clients | `agentgraph mcp-config`, `agentgraph mcp-serve` |
| Browser extension | Passive indexing from supported browser tabs | [Chrome Web Store](https://chromewebstore.google.com/detail/agentgraph-extension/iilkfclglabllelhjacijldknapbhidi?authuser=0&hl=en-AU) |
| Viewer | Visual graph inspection and manual exploration | `http://127.0.0.1:8765/viewer` |

## Commands

### Query

```bash
agentgraph search "project kickoff notes"
agentgraph query --type Message --filter platform=slack --since 12h
agentgraph get <entity-id>
agentgraph edges <entity-id>
agentgraph traverse <entity-id> --depth 2
```

### Fetch and files

```bash
agentgraph fetch gdocs <document-id>
agentgraph fetch-entity <entity-id>
agentgraph download <entity-id>
```

### Sync and connectors

```bash
agentgraph connectors
agentgraph poll
agentgraph ingest gmail
```

### MCP

```bash
agentgraph mcp-serve
agentgraph mcp-serve --transport sse --port 8808
agentgraph mcp-serve --transport streamable-http --host 0.0.0.0 --port 8808
```

See the full [command reference](docs-src/commands/index.md) and [MCP tool reference](docs-src/mcp/index.md).

## Connectors

Included connectors:

| Source | Entities | Auth | Refresh model |
| --- | --- | --- | --- |
| Slack | Channel, Message | Browser-derived cookie credentials | Browser dwell plus 5 minute polling |
| Discord | Channel, Message | Bot token | Browser dwell plus 5 minute polling |
| Google Docs | Document | Google OAuth | Browser dwell plus Drive-backed refresh |
| Google Sheets | Spreadsheet | Google OAuth | Browser dwell plus Drive-backed refresh |
| Google Drive | Folder, Document | Google OAuth | Browser dwell for folders and files, plus Drive changes polling |
| Gmail | Thread | Google OAuth | Browser dwell plus background poll and ingest |

AgentGraph is designed to be extended. Custom connectors live in separate packages, register through the connector entry point, and implement the shared `BaseConnector` interface. See [Extending](docs-src/extending.md).

## Configuration

Settings are read from environment variables and from a `.env` file in the config directory.

| Variable | Default | Description |
| --- | --- | --- |
| `AGENTGRAPH_CONFIG_DIR` | `~/.agentgraph` | Directory for config, credentials, and the default SQLite database |
| `AGENTGRAPH_BACKEND` | `sqlite` | Persistence backend. The built-in backend is `sqlite` |
| `AGENTGRAPH_BACKEND_SQLITE_PATH` | `$AGENTGRAPH_CONFIG_DIR/agentgraph.db` | SQLite database path |
| `AGENTGRAPH_SERVER_HOST` | `127.0.0.1` | Server bind address |
| `AGENTGRAPH_SERVER_PORT` | `8765` | Server port |
| `AGENTGRAPH_DWELL_THRESHOLD_SECONDS` | `3` | Seconds of focus before a fetch is triggered |
| `AGENTGRAPH_RETENTION_DAYS` | `90` | Days before an unvisited entity is garbage collected |
| `AGENTGRAPH_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model used for embeddings |

See [Configuration](docs-src/configuration.md) for the full setup.

## MCP Tools

`agentgraph mcp-serve` exposes these tool families to MCP clients:

- `list_connectors_tool`
- `search_entities_tool`
- `get_entity_tool`
- `get_edges_tool`
- `traverse_graph_tool`
- `query_by_filter_tool`
- `fetch_entity_tool`
- `fetch_entity_by_id_tool`
- `download_entity_tool`

## Contributing

See [AGENTS.md](AGENTS.md) for repo-specific development rules.

## License

See [LICENSE](LICENSE).
