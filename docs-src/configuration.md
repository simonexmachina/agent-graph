+++
title = "Configuration"
description = "Configuration directory, database settings, dwell threshold, retention, and server settings."
nav_title = "Configuration"
section = "Configuration"
order = 10
summary = "AgentGraph reads settings from environment variables and from a `.env` file in the config directory. The default setup is local-first SQLite."
output = "configuration.html"
source_path = "docs-src/configuration.md"
+++

## Config directory

The config directory defaults to `~/.agentgraph`. Change it with `AGENTGRAPH_CONFIG_DIR`.

```bash
AGENTGRAPH_CONFIG_DIR=/path/to/agentgraph agentgraph serve
```

That directory controls:

- `config.toml`
- `config.yaml` (optional alternative for connector configuration)
- `credentials.json`
- the config `.env`
- the default SQLite database path

Connector configuration that is not a secret, such as RSS feed URLs, is stored in
`config.toml` by default, or `config.yaml` if that file exists. Provider tokens and
account identifiers remain in `credentials.json`. Google records include the public
OAuth client ID that issued each refresh token, but never the packaged OAuth client
secret. Desktop OAuth client credentials distributed with AgentGraph are public
application identifiers, not a security boundary.

## Storage backend

AgentGraph stores the graph in SQLite by default, and the install and quickstart docs assume this setup.

## Core settings

### `AGENTGRAPH_CONFIG_DIR`

Default: `~/.agentgraph`

Directory for AgentGraph config, credentials, and the default SQLite database.

### `AGENTGRAPH_BACKEND`

Default: `sqlite`

Persistence backend. The built-in backend is `sqlite`.

### `AGENTGRAPH_BACKEND_SQLITE_PATH`

Default: `$AGENTGRAPH_CONFIG_DIR/agentgraph.db`

SQLite database path.

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

Default: `BAAI/bge-small-en-v1.5`

FastEmbed model used for embeddings.

## Slack workspace filter

If you only want Slack data from one workspace, set `AGENTGRAPH_SLACK_WORKSPACE_ID`.

```bash
AGENTGRAPH_SLACK_WORKSPACE_ID=T04T4TH8W agentgraph serve
```
