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

## Returns

- connector-defined result JSON
- connector-owned help when `args` is `["--help"]` or `["help"]`
- an error message if the source or connector command is invalid
