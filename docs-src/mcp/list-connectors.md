+++
title = "list_connectors_tool"
description = "MCP reference for list_connectors_tool."
nav_title = "list_connectors_tool"
section = "MCP"
order = 11
summary = "Call this first when an agent needs to know which connectors exist, their credential state where applicable, and which platform values are valid elsewhere."
output = "mcp/list-connectors.html"
source_path = "docs-src/mcp/list-connectors.md"
+++

## Signature

```text
list_connectors_tool() -> JSON string
```

## Returns

- connector `source`
- `description`
- `auth_status` and `auth_detail`, or null for connectors that do not use credentials
- `url_patterns`
- polling metadata and sync summary
