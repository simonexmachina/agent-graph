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

<table>
  <thead>
    <tr>
      <th>Variable</th>
      <th>Default</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>AGENTGRAPH_CONFIG_DIR</code></td>
      <td><code>~/.agentgraph</code></td>
      <td>Directory for AgentGraph config, credentials, and the default SQLite database.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_BACKEND</code></td>
      <td><code>sqlite</code></td>
      <td>Persistence backend: <code>sqlite</code> or <code>postgres</code>.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_BACKEND_SQLITE_PATH</code></td>
      <td><code>$AGENTGRAPH_CONFIG_DIR/agentgraph.db</code></td>
      <td>SQLite database path.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_DATABASE_URL</code></td>
      <td><code>postgresql://agentgraph:agentgraph@localhost:5432/agentgraph</code></td>
      <td>PostgreSQL connection URL when backend is <code>postgres</code>.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_SERVER_HOST</code></td>
      <td><code>127.0.0.1</code></td>
      <td>Server bind address.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_SERVER_PORT</code></td>
      <td><code>8765</code></td>
      <td>Server port.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_DWELL_THRESHOLD_SECONDS</code></td>
      <td><code>3</code></td>
      <td>Seconds of focus before a fetch is triggered.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_RETENTION_DAYS</code></td>
      <td><code>90</code></td>
      <td>Days before an unvisited entity is garbage collected.</td>
    </tr>
    <tr>
      <td><code>AGENTGRAPH_EMBEDDING_MODEL</code></td>
      <td><code>all-MiniLM-L6-v2</code></td>
      <td>Sentence-transformers model used for embeddings.</td>
    </tr>
  </tbody>
</table>

## PostgreSQL

SQLite is the default backend. For PostgreSQL setup, environment variables, and switching guidance, see [PostgreSQL](/postgresql.html).

## Slack workspace filter

If you only want Slack data from one workspace, set `AGENTGRAPH_SLACK_WORKSPACE_ID`.

```bash
AGENTGRAPH_SLACK_WORKSPACE_ID=T04T4TH8W agentgraph serve
```
