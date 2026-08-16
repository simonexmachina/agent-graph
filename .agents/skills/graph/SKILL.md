---
name: graph
description: Use AgentGraph through its CLI or MCP tools to search and traverse selected local context, retrieve full source-backed evidence, fetch missing or stale resources, and troubleshoot connector availability.
---

# /graph - AgentGraph CLI skill

AgentGraph is a local knowledge graph for the agent the user already uses. It stores
selected messages, documents, people, feeds, pages, and relationships; the agent is
responsible for searching that graph, comparing evidence, and explaining its reasoning.

Prefer the `agentgraph` CLI when a shell is available. Use the equivalent MCP tools
when AgentGraph is connected directly to the agent. Do not query AgentGraph's SQLite
database or connector internals directly.

## Commands that use localhost

`agentgraph poll` and connector or authentication commands that queue a poll or
historical ingest call the configured local AgentGraph HTTP server. If a sandbox blocks
one of these commands, request permission to contact that localhost server and retry
the command after approval.

## Investigation workflow

1. Discover likely entities with `agentgraph search "<query>" --json` or
   `search_entities_tool`.
2. Open promising results with `agentgraph get <target> --json` or
   `get_entity_tool` to read full content and source metadata. Search and query results
   contain bounded snippets and set `content_truncated` when content was shortened.
3. Follow relationships with `agentgraph edges`, `agentgraph traverse`,
   `get_edges_tool`, or `traverse_graph_tool`.
4. If an entity is a stub, or known context is stale, resolve or re-fetch it through
   the owning connector and then repeat the read or traversal.
5. Compare source dates and contents. Distinguish source facts from inference and cite
   each source URL or entity identifier used.

Start with search unless the user already supplied a graph ID, platform reference, or
known indexed URL. Use structured `query` only when the entity type or filters are
already known.

## Context lifecycle

- **Connect** is setup: installed connectors and their authentication/configuration
  determine which selected sources AgentGraph can access.
- **Observe** records human attention to a supported browser URL and triggers a
  targeted connector fetch.
- **Fetch** retrieves missing or stale context at the agent's request.
- **Refresh** uses polling or connector-owned ingest commands to update configured or
  already-known context.

Only browser observation updates `observed_at`. Direct fetch, polling, and ingest can
change graph content without implying that the human viewed it.

## Evidence rules

- Use full entity content before making a source-backed claim; do not treat a search
  snippet as the complete source.
- Treat an entity with no title and no content as an unresolved stub.
- Use source timestamps for chronology. `created_at` and `updated_at` describe the
  local graph record; `source_created_at` and `source_updated_at` describe the source.
- Chat uploads live on `Message.metadata.attachments`. Gmail attachments are
  `Document` stubs referenced by their owning `Email` and are downloaded separately.
- Inspect connector and auth state only when freshness matters, a fetch is required,
  or a graph operation reports a connector or credential problem.
- Never merge Person entities without user confirmation. Treat delete, credential
  removal, and unbookmarking as destructive actions.

## References

- Read [references/commands.md](references/commands.md) for CLI syntax, MCP mappings,
  target formats, stub resolution, and result-size behavior.
- Read [references/data-model.md](references/data-model.md) for entity types, edges,
  attachment representation, timestamps, and retention semantics.
- Read [references/operations.md](references/operations.md) for connectors, auth,
  polling, connector-owned commands, downloads, bookmarks, deletion, person merging,
  server setup, and skill installation.
