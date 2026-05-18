+++
title = "PostgreSQL"
description = "Run AgentGraph with PostgreSQL instead of the default SQLite backend."
nav_title = "PostgreSQL"
section = "Start"
order = 45
summary = "AgentGraph uses SQLite by default, but the backend is pluggable. This page covers when to switch to PostgreSQL and how to configure it."
output = "postgresql.html"
source_path = "docs-src/postgresql.md"
+++

## When to use it

The docs assume SQLite unless a page says otherwise. SQLite is the default backend and the simplest way to run AgentGraph on one machine.

Use PostgreSQL when you want AgentGraph to talk to a separate database service instead of storing the graph in a local SQLite file.

## Backend model

AgentGraph's storage backend is pluggable. The CLI, viewer, browser extension flow, and MCP server all use the same backend abstraction, so switching backends does not change how you search, fetch, serve, or connect clients.

Set `AGENTGRAPH_BACKEND=postgres` to select PostgreSQL. Leave it unset, or set it to `sqlite`, to keep using the default SQLite backend.

## Quick setup

Generate a local PostgreSQL service configuration and save the backend settings:

```bash
agentgraph use-postgres
```

That command:

- writes `docker-compose.yml` to the current directory
- saves `AGENTGRAPH_BACKEND=postgres` in the AgentGraph config `.env`
- saves `AGENTGRAPH_DATABASE_URL` in the AgentGraph config `.env`
- prints the next steps for starting PostgreSQL and restarting AgentGraph

If you already have PostgreSQL running elsewhere, provide your own connection URL:

```bash
agentgraph use-postgres --url postgresql://user:password@db.example.com:5432/agentgraph
```

To print the generated Compose file instead of writing it to disk:

```bash
agentgraph use-postgres --compose-out -
```

## Environment variables

PostgreSQL uses these settings:

- `AGENTGRAPH_BACKEND=postgres`
- `AGENTGRAPH_DATABASE_URL=postgresql://agentgraph:agentgraph@localhost:5432/agentgraph`

SQLite-specific settings such as `AGENTGRAPH_BACKEND_SQLITE_PATH` are ignored when the backend is `postgres`.

## Switching back

To go back to SQLite, set:

```bash
AGENTGRAPH_BACKEND=sqlite
```

You can keep `AGENTGRAPH_DATABASE_URL` in your `.env`; it is only used when the backend is `postgres`.

If you need to copy data between backends, use [`agentgraph migrate`](/commands/migrate.html).
