+++
title = "poll_connectors_tool"
description = "MCP reference for poll_connectors_tool."
nav_title = "poll_connectors_tool"
section = "MCP"
order = 22
summary = "Use `poll_connectors_tool` to trigger background polling for one connector or all polling connectors."
output = "mcp/poll-connectors.html"
source_path = "docs-src/mcp/poll-connectors.md"
+++

## Signature

```text
poll_connectors_tool(source = null) -> JSON string
```

## Arguments

- `source`: optional connector source. Omit it to poll every connector with a configured `poll_interval`.

## Returns

- `polled`: connector sources whose background poll was started
- an error message if a requested connector source is not registered
