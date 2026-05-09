# /graph — AgentGraph CLI skill

Use the `agentgraph` CLI to query the local knowledge graph. Always prefer the CLI over direct Python/DB access.

## Commands

```bash
# Semantic search across entities
agentgraph search "<query>" [--type <type>] [--platform <platform>] [--limit N] [--json]

# Fetch full entity details by ID, UUID prefix, or platform ref (platform/entity_id)
agentgraph get <entity-id|platform/ref> --resolve [--json]

# List edges for an entity
agentgraph edges <entity-id|platform/ref> [--type <edge-type>] [--direction in|out|both] [--json]

# Traverse the graph from a starting entity
agentgraph traverse <entity-id|platform/ref> --resolve [--depth N] [--json]

# Filter entities by type and metadata
agentgraph query --type <entity-type> [--filter key=value] [--since 12h|30m|2d] [--mine] [--has-attachments] [--limit N] [--order-by created_at|updated_at|last_accessed] [--json]

# Trigger a connector fetch for a platform entity (by platform + platform-specific ID)
agentgraph fetch <platform> <resource-id> [--json]

# Trigger a connector re-fetch for an entity by its internal UUID
agentgraph fetch-entity <entity-id> [--json]

# Trigger a background poll for one or all connectors
agentgraph poll [<source>] [--json]   # source: slack, gmail, discord, drive — omit for all

# Run a one-shot bulk ingest for a connector (all data within the retention window, beyond what poll covers)
agentgraph ingest <source> [--json]   # e.g. gmail — fetches all labels, not just inbox

# List installed connectors and their auth status
agentgraph connectors [--json] # auth_status/auth_detail, url_patterns, polls; run first to check auth

# Authenticate connectors
agentgraph auth google        # Google OAuth2; use when Google auth_status is missing/invalid
agentgraph auth slack         # Slack cookie credentials
agentgraph auth discord       # Discord bot token

# Server
agentgraph serve [--reload]
agentgraph mcp-serve
```

## Entity types

| Type | Contains |
|---|---|
| `Message` | Chat messages (Discord, Slack, Gmail). **Images and file uploads are attachments on Message entities** — stored in `metadata.attachments` (JSON array with `url`, `filename`, `content_type`, `width`, `height`). Use `--has-attachments` to filter to messages with files. |
| `Document` | Text documents (Google Docs, etc.). Does NOT contain image attachments. |
| `Channel` | Chat channels and DM threads. |
| `Task` | Tasks or to-do items. |
| `Project` | Project/repository containers. |

To find images uploaded this week: `agentgraph query --type Message --has-attachments --since 7d --json`

## Notes

- The CLI automatically falls back to local DB if the server isn't running (prints a dim warning)
- Use `--json` when you need to parse results programmatically
- Entity IDs accept: full UUID, UUID prefix, or platform ref (`slack/C123`, `gdocs/doc-id`, `discord/dm/456`)
- Server logs: `/tmp/agentgraph.log`

## Stub Entities

An entity is a **stub** when it has no title and no content — it was referenced in an edge but never fetched from its source. Using `--resolve` (default for `get` and `traverse`) automatically fetches stubs from their source before returning. If you omitted `--resolve` and get empty results, re-run with it or use `agentgraph fetch-entity <entity-id>` then re-fetch.

## Workflow

When the user asks about graph data:
1. Run `agentgraph connectors --json` to verify the relevant connector is installed and authenticated
2. If Google has `auth_status: "invalid"` or `"missing"`, tell the user to run `agentgraph auth google`
3. Run the appropriate `agentgraph` command with `--json` to get structured output
4. Use `edges` or `traverse` to follow relationships when needed
