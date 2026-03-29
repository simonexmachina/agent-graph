# /graph — AgentGraph CLI skill

Use the `agentgraph` CLI to query the local knowledge graph. Always prefer the CLI over direct Python/DB access.

## Commands

```bash
# Semantic search across entities
agentgraph search "<query>" [--type <type>] [--limit N] [--json]

# Fetch full entity details by ID, UUID prefix, or platform ref (platform/entity_id)
agentgraph get <entity-id|platform/ref> [--json]

# List edges for an entity
agentgraph edges <entity-id|platform/ref> [--type <edge-type>] [--direction in|out|both] [--json]

# Traverse the graph from a starting entity
agentgraph traverse <entity-id|platform/ref> [--depth N] [--json]

# Filter entities by type and metadata
agentgraph query --type <entity-type> [--filter key=value] [--since 12h|30m|2d] [--mine] [--limit N] [--order-by created_at|updated_at|last_accessed] [--json]

# Trigger a connector fetch for a platform entity (by platform + platform-specific ID)
agentgraph fetch <platform> <resource-id> [--json]

# Trigger a connector re-fetch for an entity by its internal UUID
agentgraph fetch-entity <entity-id> [--json]

# Server
agentgraph serve [--reload]
agentgraph mcp-serve
```

## Notes

- The CLI automatically falls back to local DB if the server isn't running (prints a dim warning)
- Use `--json` when you need to parse results programmatically
- Entity IDs accept: full UUID, UUID prefix, or platform ref (`slack/C123`, `gdocs/doc-id`, `discord/dm/456`)
- Server logs: `/tmp/agentgraph.log`

## Workflow

When the user asks about graph data:
1. Run the appropriate `agentgraph` command with `--json` to get structured output
2. Parse and summarise the results for the user
3. Use `edges` or `traverse` to follow relationships when needed
