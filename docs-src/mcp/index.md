+++
title = "MCP tools"
description = "Reference for the AgentGraph MCP tool surface."
nav_title = "MCP tools"
section = "MCP"
order = 10
summary = "These are the tools exposed by `agentgraph mcp-serve`. They mirror the graph operations available in the CLI, but are shaped for agent clients."
output = "mcp/index.html"
source_path = "docs-src/mcp/index.md"
+++

## Discovery

- [`list_connectors_tool`](/mcp/list-connectors.html) - inspect installed connectors, auth state, and valid platform values.

## Query and traversal

- [`search_entities_tool`](/mcp/search-entities.html) - hybrid search across the graph.
- [`get_entity_tool`](/mcp/get-entity.html) - retrieve one entity by UUID.
- [`get_edges_tool`](/mcp/get-edges.html) - inspect direct edges.
- [`traverse_graph_tool`](/mcp/traverse-graph.html) - build a local subgraph from one entity.
- [`query_by_filter_tool`](/mcp/query-by-filter.html) - structured filtering by type and metadata.

## Fetch and files

- [`fetch_entity_tool`](/mcp/fetch-entity.html) - fetch by platform and platform ID.
- [`fetch_entity_by_id_tool`](/mcp/fetch-entity-by-id.html) - fetch by internal entity UUID.
- [`download_entity_tool`](/mcp/download-entity.html) - download the source file behind an entity.
- [`delete_entity_tool`](/mcp/delete-entity.html) - remove an entity and its connected edges.

## State

- `bookmark_entity_tool(entity_id, bookmarked=false)` clears bookmark protection for an existing entity.
