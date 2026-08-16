# AgentGraph operations

## Availability and authentication

```bash
agentgraph connectors [--verify] [--json]
agentgraph auth [--verify] [--json] status
agentgraph auth <provider> [--add] [--account <account-id>]
agentgraph auth remove <provider> [--account <account-id>] [--json]
```

Use `agentgraph connectors --json` to discover installed connector source names,
valid platform values, URL ownership, polling delegation, and sync state. Do not rely
on a hardcoded platform list. Use `--verify` only when a live provider check is
needed.

MCP equivalents are `list_connectors_tool`, `list_auth_providers_tool`,
`authenticate_provider_tool`, and `remove_auth_provider_tool`.

## Fetch and refresh

```bash
agentgraph fetch <platform> <resource-id> [--json]
agentgraph fetch-entity <entity-id> [--json]
agentgraph poll [<source>] [--json]
agentgraph connector <source> <command> [args...] [--json]
agentgraph connector <source> --help
```

The MCP equivalents are `fetch_entity_tool`, `fetch_entity_by_id_tool`,
`poll_connectors_tool`, and `run_connector_command_tool`.

Fetch persists the connector's complete returned batch before reporting counts and
does not update `observed_at`. Poll reports `polled`, `already_running`, and `skipped`.
A connector can be refreshed by another connector, so also inspect `polled_by` and
`sync` in connector status.

Historical ingest is connector-owned. Discover it through connector help. For
example, Gmail exposes:

```bash
agentgraph connector gmail ingest [--account <account-id>] [--json]
```

The MCP form is `run_connector_command_tool("gmail", ["ingest", ...])`. There is no
top-level `agentgraph ingest` command or `ingest_connector_tool`.

## Files and retained context

```bash
agentgraph download <entity-id|platform/ref> [--output <file-or-dir>] [--json]
agentgraph bookmark <entity-id|platform/ref|url> [--remove] [--json]
agentgraph delete <entity-id|platform/ref|url> [--json]
agentgraph unify-persons <primary-person-id> <duplicate-person-id>... [--json]
```

Use `download_entity_tool`, `bookmark_entity_tool`, `delete_entity_tool`, and
`unify_persons_tool` through MCP. Confirm identity before person unification. The
first Person is canonical and keeps its ID. Deletion removes connected edges.

## Server and skill setup

Graph data commands require the local AgentGraph server. If it is unavailable, follow
the environment's process-management instructions; otherwise `agentgraph serve`
starts it. Do not start a duplicate foreground server when a service manager already
owns the process.

```bash
agentgraph mcp-config
agentgraph mcp-serve
agentgraph install-skill [graph] [--target user|project] [--claude] [--force] [--json]
```

The MCP skill installer is `install_skill_tool(skill, target, force, claude)`.
