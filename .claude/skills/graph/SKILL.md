---
name: graph
description: Use the AgentGraph CLI to query the local knowledge graph, inspect connectors, fetch entities, traverse relationships, and configure MCP access.
---

# /graph — AgentGraph CLI skill

Use the `agentgraph` CLI to query the local knowledge graph. Always prefer the CLI over direct Python/DB access.

## Commands

```bash
# Semantic search across entities
agentgraph search "<query>" [--type <type>] [--platform <platform>] [--limit N] [--json]

# Fetch full existing entity details by ID, UUID prefix, platform ref, or URL
agentgraph get <entity-id|platform/ref|url> --resolve [--json]

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

# Download an entity's source file using connector auth
agentgraph download <entity-id|platform/ref> [--output <file-or-dir>] [--json]

# Bookmark an entity or retrieve and bookmark an HTTP(S) URL; use --remove to clear bookmark protection
agentgraph bookmark <entity-id|platform/ref|url> [--remove] [--json]

# Delete an entity from the graph
agentgraph delete <entity-id|platform/ref|url> [--json]

# Merge duplicate Person entities that refer to the same human
agentgraph unify-persons <primary-person-id> <duplicate-person-id>... [--json]

# Trigger a background poll for one or all connectors
agentgraph poll [<source>] [--json]   # source: slack, gmail, discord, drive, rss — omit for all

# Run a one-shot bulk ingest for a connector (all data within the retention window, beyond what poll covers)
agentgraph ingest <source> [--json]   # e.g. gmail, rss

# List installed connectors and their auth/sync status
agentgraph connectors [--json] # auth_provider, auth_status/auth_detail, url_patterns, polls, poll_delegates, polled_by, sync, last_synced_at

# Run a connector-owned command
agentgraph connector <source> <command> [args...] [--json] # e.g. agentgraph connector rss add https://simonwillison.net/atom/everything/
agentgraph connector <source> --help
agentgraph connector rss add <feed-or-html-url> [feed-or-html-url...] [--json] # validates feeds; HTML pages/files resolve via RSS/Atom <link>
agentgraph connector rss remove <feed-url> [feed-url...] [--json] # removes exact configured feed URLs
agentgraph connector rss import-opml <file.opml> [--all | --select 1,3-5] [--json] # omit flags for checkbox selection

# Show auth provider state (dedupes shared providers like Google)
agentgraph auth [--json] status # provider, connectors[], auth_status/auth_detail, accounts[]

# Authenticate connectors/providers
agentgraph auth google [--add] [--account <account-id>]   # Google OAuth2; use when Google auth_status is missing/invalid
agentgraph auth slack [--add] [--account <account-id>]    # Slack cookie credentials
agentgraph auth discord [--add] [--account <account-id>]  # Discord bot token
agentgraph auth rss [--add] [--account <account-id>]      # RSS/Atom feed URLs interactively

# Server
agentgraph serve [--reload]
agentgraph mcp-serve
agentgraph mcp-config   # stdio config for Claude Desktop/Claude Code; ChatGPT uses a tunneled HTTPS /mcp endpoint
```

## MCP tool equivalents

When using AgentGraph through MCP instead of the CLI, use these equivalent tools:

```text
agentgraph connectors              -> list_connectors_tool()
agentgraph auth [--json] status    -> list_auth_providers_tool()
agentgraph connector <source> ...  -> run_connector_command_tool(source, args)
agentgraph search ...              -> search_entities_tool(...)
agentgraph get ...                 -> get_entity_tool(entity_id)
agentgraph edges ...               -> get_edges_tool(entity_id, edge_type, direction)
agentgraph traverse ...            -> traverse_graph_tool(entity_id, max_depth)
agentgraph query ...               -> query_by_filter_tool(...)
agentgraph fetch ...               -> fetch_entity_tool(platform, resource_id)
agentgraph fetch-entity ...        -> fetch_entity_by_id_tool(entity_id)
agentgraph download ...            -> download_entity_tool(entity_id, output_path)
agentgraph poll [source]           -> poll_connectors_tool(source)
agentgraph ingest <source>         -> ingest_connector_tool(source)
agentgraph bookmark ...            -> bookmark_entity_tool(entity_id, bookmarked)
agentgraph delete ...              -> delete_entity_tool(entity_id)
agentgraph unify-persons ...       -> unify_persons_tool(primary_entity_id, duplicate_entity_ids)
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
- Bookmark targets accept: full UUID, UUID prefix, platform ref (`slack/T123/C123`, `gdocs/doc-id`, `discord/dm/456`), or HTTP(S) URL
- `agentgraph bookmark --remove <entity-id|platform/ref|url>` clears bookmark protection for existing graph entities
- Delete targets accept: full UUID, UUID prefix, platform ref, or HTTP(S) URL. Connected edges are removed with the entity.
- Use `agentgraph download` for source files stored behind connector auth, such as Drive PDFs or exported Google Docs/Sheets
- Use `agentgraph bookmark` for entities or HTTP(S) URLs that should survive retention-window garbage collection
- Use `agentgraph unify-persons` only after confirming two or more `Person` entities are the same human; the first argument is the canonical person to keep
- `polls: false` does not always mean stale: check `polled_by` / `sync` for connectors refreshed by another connector, e.g. `gdocs` and `gsheets` are refreshed via the `gdrive` Drive Changes poll
- Server logs go to stdout unless the process manager redirects them elsewhere

## Stub Entities

An entity is a **stub** when it has no title and no content — it was referenced in an edge but never fetched from its source. Using `--resolve` (default for `get` and `traverse`) automatically fetches stubs from their source before returning. If you omitted `--resolve` and get empty results, re-run with it or use `agentgraph fetch-entity <entity-id>` then re-fetch.

## Workflow

When the user asks about graph data:
1. Run `agentgraph connectors --json` to verify the relevant connector is installed and to inspect its last sync state
2. Run `agentgraph auth --json status` to inspect provider-level authentication, especially for shared auth like Google
3. If Google has `auth_status: "invalid"` or `"missing"`, tell the user to run `agentgraph auth google`
4. Run the appropriate `agentgraph` command with `--json` to get structured output
5. Use `edges` or `traverse` to follow relationships when needed
