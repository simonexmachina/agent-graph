+++
title = "Configuration"
description = "Configuration directory, database settings, dwell threshold, retention, and server settings."
nav_title = "Configuration"
section = "Start"
order = 40
summary = "AgentGraph reads settings from environment variables and from a `.env` file in the config directory. The default setup is local-first SQLite, but the backend is pluggable."
output = "configuration.html"
source_path = "docs-src/configuration.md"
+++

## Config directory

The config directory defaults to `~/.agentgraph`. Change it with `AGENTGRAPH_CONFIG_DIR`.

```bash
AGENTGRAPH_CONFIG_DIR=/path/to/agentgraph agentgraph serve
```

That directory controls:

- `credentials.json`
- the config `.env`
- the default SQLite database path

## Storage backend

AgentGraph uses a pluggable backend for graph storage.

- `sqlite` is the default and is assumed throughout the install and quickstart docs.
- `postgres` is available when you want AgentGraph to use a separate PostgreSQL service.

The CLI, viewer, and MCP server work the same way regardless of which backend you choose.

## Core settings

### `AGENTGRAPH_CONFIG_DIR`

Default: `~/.agentgraph`

Directory for AgentGraph config, credentials, and the default SQLite database.

### `AGENTGRAPH_BACKEND`

Default: `sqlite`

Persistence backend: `sqlite` or `postgres`.

### `AGENTGRAPH_BACKEND_SQLITE_PATH`

Default: `$AGENTGRAPH_CONFIG_DIR/agentgraph.db`

SQLite database path.

### `AGENTGRAPH_DATABASE_URL`

Default: `postgresql://agentgraph:agentgraph@localhost:5432/agentgraph`

PostgreSQL connection URL when backend is `postgres`.

### `AGENTGRAPH_SERVER_HOST`

Default: `127.0.0.1`

Server bind address.

### `AGENTGRAPH_SERVER_PORT`

Default: `8765`

Server port.

### `AGENTGRAPH_DWELL_THRESHOLD_SECONDS`

Default: `3`

Seconds of focus before a fetch is triggered.

### `AGENTGRAPH_RETENTION_DAYS`

Default: `90`

Days before an unvisited entity is garbage collected.

### `AGENTGRAPH_EMBEDDING_MODEL`

Default: `all-MiniLM-L6-v2`

Sentence-transformers model used for embeddings.

## PostgreSQL

SQLite is the default backend. For PostgreSQL setup, environment variables, and switching guidance, see [PostgreSQL](/postgresql.html).

## Slack workspace filter

If you only want Slack data from one workspace, set `AGENTGRAPH_SLACK_WORKSPACE_ID`.

```bash
AGENTGRAPH_SLACK_WORKSPACE_ID=T04T4TH8W agentgraph serve
```
