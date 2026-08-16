# Query and traversal commands

## CLI

```bash
agentgraph search "<query>" [--type <type>] [--platform <platform>] [--limit N] [--min-score N] [--json]
agentgraph query --type <entity-type> [--filter key=value] [--since 12h|30m|2d] [--mine] [--has-attachments] [--limit N] [--order-by created_at|updated_at|source_created_at|source_updated_at|observed_at|synced_at] [--json]
agentgraph get <entity-id|platform/ref|url> [--resolve] [--json]
agentgraph edges <entity-id|platform/ref> [--type <edge-type>] [--direction in|out|both] [--json]
agentgraph traverse <entity-id|platform/ref> [--resolve] [--depth 0..4] [--json]
```

`get` and `traverse` do not resolve stubs unless `--resolve` is supplied. Depth 0
returns only the starting entity; depths 1 through 4 include that many relationship
hops.

Use `--json` when results will be parsed programmatically. Search and query return
bounded content snippets with `content_truncated`; use `get` for the complete entity.

Targets accepted by `get` are full UUIDs, unambiguous UUID prefixes, platform
references such as `slack/T123/C123`, and indexed HTTP(S) URLs. `edges` and `traverse`
accept full UUIDs, unambiguous UUID prefixes, and platform references.

## MCP equivalents

```text
agentgraph search ...    -> search_entities_tool(query, entity_types, platform, limit, min_score, refresh)
agentgraph query ...     -> query_by_filter_tool(entity_type, filters, since, authored_by_me, has_attachments, limit, order_by, refresh)
agentgraph get ...       -> get_entity_tool(entity_id, resolve)
agentgraph edges ...     -> get_edges_tool(entity_id, edge_type, direction)
agentgraph traverse ...  -> traverse_graph_tool(entity_id, max_depth, resolve)
```

MCP search and query default to `refresh=false`; set it only when fresh
connector-owned presentation metadata is needed. It does not replace a targeted
source fetch for stale content.

## Stubs

An entity is a stub when it has neither a title nor content. With the CLI, pass
`--resolve` to `get` or `traverse`. With MCP, set `resolve=true`, or call
`fetch_entity_by_id_tool` for the stub UUID and repeat the original operation.

For a known platform resource that is absent from the graph, use `agentgraph fetch
<platform> <resource-id>` or `fetch_entity_tool(platform, resource_id)`.
