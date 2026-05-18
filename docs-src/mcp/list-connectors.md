+++
title = "list_connectors_tool"
description = "MCP reference for list_connectors_tool."
nav_title = "list_connectors_tool"
section = "MCP"
order = 11
summary = "Call this first when an agent needs to know which connectors exist, whether they are authenticated, and which platform values are valid elsewhere."
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
- `auth_status` and `auth_detail`
- `url_patterns`
- polling metadata and sync summary
