+++
title = "run_connector_command_tool"
description = "MCP reference for run_connector_command_tool."
nav_title = "run_connector_command_tool"
section = "MCP"
order = 14
summary = "Use `run_connector_command_tool` to run connector-owned commands through the same generic dispatch as `agentgraph connector`."
output = "mcp/run-connector-command.html"
source_path = "docs-src/mcp/run-connector-command.md"
+++

## Signature

```text
run_connector_command_tool(source, args) -> JSON string
```

## Arguments

- `source`: connector source, such as `rss`
- `args`: connector-owned command and arguments, such as `["add", "https://example.com/feed.xml"]`

Historical ingest is connector-owned. Gmail exposes `["ingest"]` and
`["ingest", "--account", "user@example.com"]`; there is no separate
`ingest_connector_tool`. The web connector accepts
`["fetch", "https://example.com/page", "--compact"]` for a one-off compact HTML
fetch, `["watch", "<url-or-prefix>"]` to add a browser observation rule, and
`["unwatch", "<url-or-prefix>"]` to remove one. Discover other command sets with
`args=["--help"]`.

## Returns

- connector-defined result JSON
- connector-owned help when `args` is `["--help"]` or `["help"]`
- an error message if the source or connector command is invalid
