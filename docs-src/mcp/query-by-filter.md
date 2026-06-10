+++
title = "query_by_filter_tool"
description = "MCP reference for query_by_filter_tool."
nav_title = "query_by_filter_tool"
section = "MCP"
order = 18
summary = "Use `query_by_filter_tool` when the agent knows the entity type and wants deterministic filtering rather than ranked search."
output = "mcp/query-by-filter.html"
source_path = "docs-src/mcp/query-by-filter.md"
+++

## Signature

```text
query_by_filter_tool(entity_type, filters=None, since=None, authored_by_me=False, has_attachments=False, limit=50, order_by="created_at") -> JSON string
```

## Notes

- `Message` is the correct entity type for uploaded files and images
- `has_attachments=True` only applies to `Message`
