+++
title = "ingest_connector_tool"
description = "MCP reference for ingest_connector_tool."
nav_title = "ingest_connector_tool"
section = "MCP"
order = 24
summary = "Use `ingest_connector_tool` to trigger a connector's one-shot background ingest."
output = "mcp/ingest-connector.html"
source_path = "docs-src/mcp/ingest-connector.md"
+++

## Signature

```text
ingest_connector_tool(source) -> JSON string
```

## Arguments

- `source`: connector source to ingest, such as `gmail` or `rss`

## Returns

- `source`
- `status: "started"`
- an error message if the connector source is not registered
