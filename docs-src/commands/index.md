+++
title = "Command docs index"
description = "Command reference for the AgentGraph CLI and MCP workflows."
nav_title = "Command docs"
section = "Reference"
order = 10
summary = "The CLI and MCP server expose the same graph operations. Use the terminal directly for local work, or connect an MCP client to run the same actions from an assistant."
output = "commands/index.html"
source_path = "docs-src/commands/index.md"
aliases = ["commands.html"]
+++

## Query

- `agentgraph search` - hybrid semantic and lexical search across the local graph.
- `agentgraph query` - filter entities by type, ownership, time window, and attachment presence.
- `agentgraph get` - return one entity by UUID, UUID prefix, or platform reference.
- `agentgraph edges` - list connected edges for one entity, filtered by direction and edge type.
- `agentgraph traverse` - walk outward from an entity across graph edges.

```bash
agentgraph search "project kickoff notes" --type Document --limit 10 --json
agentgraph query --type Message --filter platform=slack --since 24h --mine --limit 20
agentgraph get abc123ef --json
agentgraph traverse abc123ef --depth 2 --resolve --json
```

## Fetch

- `agentgraph fetch` - trigger a connector fetch by source and platform-specific identifier.
- `agentgraph fetch-entity` - re-fetch a known entity by internal UUID.

```bash
agentgraph fetch slack C0J2L41FT
agentgraph fetch gdocs 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
agentgraph fetch-entity abc123ef-9d6b-4bbe-b5ab-200faecb70e9 --json
```

## Sync

- `agentgraph poll` - run background polling immediately for one connector or all installed connectors.
- `agentgraph ingest` - run a one-shot historical ingest where the connector supports it.

```bash
agentgraph poll
agentgraph poll slack
agentgraph ingest gmail
```

## Connector status

- `agentgraph connectors` - list installed connectors, auth status, URL patterns, and whether they poll.

```bash
agentgraph connectors
agentgraph connectors --json
```

## Authentication

- `agentgraph onboard` - walk through auth setup for every installed connector.
- `agentgraph auth` - authenticate a specific connector directly.

```bash
agentgraph onboard
agentgraph auth google
agentgraph auth slack
agentgraph auth discord
```

## Server and MCP

- `agentgraph serve` - start the local HTTP server, connector pollers, and viewer.
- `agentgraph mcp-config` - print the client config snippet for local and remote MCP clients.
- `agentgraph mcp-serve` - run the MCP server over stdio, SSE, or streaming HTTP.

```bash
agentgraph serve
agentgraph mcp-config
agentgraph mcp-serve --transport sse --port 8808
agentgraph mcp-serve --transport streamable-http --port 8808
```
