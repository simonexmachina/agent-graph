+++
title = "Commands"
description = "Command reference for the AgentGraph CLI and MCP workflows."
nav_title = "Commands"
section = "Reference"
order = 10
summary = "The CLI is the operator-facing surface for the local graph. Each command now has its own page so flags, examples, and adjacent workflows stay readable."
output = "commands/index.html"
source_path = "docs-src/commands/index.md"
aliases = ["commands.html"]
+++

## Query

- [`search`](/commands/search.html) - hybrid semantic and lexical search.
- [`query`](/commands/query.html) - structured filtering by entity type, metadata, time, and attachments.
- [`get`](/commands/get.html) - fetch one entity by UUID, prefix, or platform ref.
- [`edges`](/commands/edges.html) - list connected graph edges for one entity.
- [`traverse`](/commands/traverse.html) - walk the neighborhood around one entity.

## Fetch and files

- [`fetch`](/commands/fetch.html) - trigger connector fetch by platform and platform ID.
- [`fetch-entity`](/commands/fetch-entity.html) - re-fetch by internal entity UUID.
- [`download`](/commands/download.html) - download the source file for a graph entity.

## Sync and connectors

- [`connectors`](/commands/connectors.html) - inspect installed connectors and auth state.
- [`poll`](/commands/poll.html) - run background polling now.
- [`ingest`](/commands/ingest.html) - run a one-shot historical ingest where supported.

## Auth and setup

- [`onboard`](/commands/onboard.html) - walk connector auth interactively.
- [`auth`](/commands/auth.html) - authenticate a specific platform connector.

## Server and transport

- [`serve`](/commands/serve.html) - run the local AgentGraph HTTP server and pollers.
- [`mcp-config`](/commands/mcp-config.html) - print MCP client configuration.
- [`mcp-serve`](/commands/mcp-serve.html) - run the MCP server over stdio, SSE, or streaming HTTP.
- [`migrate`](/commands/migrate.html) - migrate graph data between backends.
- [`use-postgres`](/commands/use-postgres.html) - switch to PostgreSQL and emit compose scaffolding.

## Related

- [MCP tools](/mcp/) for the tool pages exposed to agent clients.
