+++
title = "query_by_filter_tool"
description = "MCP reference for query_by_filter_tool."
nav_title = "query_by_filter_tool"
section = "MCP"
order = 19
summary = "Use `query_by_filter_tool` when the agent knows the entity type and wants deterministic filtering rather than ranked search."
output = "mcp/query-by-filter.html"
source_path = "docs-src/mcp/query-by-filter.md"
+++

## Signature

```text
query_by_filter_tool(entity_type, filters=null, since=null, authored_by_me=false, has_attachments=false, limit=50, order_by="created_at", refresh=false) -> JSON string
```

## Notes

- `Message` is the correct entity type for chat-style uploaded files and images
- `has_attachments=True` only applies to `Message`
- Gmail email attachments are represented as Gmail `Document` stubs referenced by the owning `Email`
- current entity types are `Channel`, `Document`, `Email`, `Folder`, `Message`,
  `Person`, `Spreadsheet`, `Task`, and `Video`
- scope by source with a column filter such as `filters={"platform": "gmail"}`
- results contain bounded content and set `content_truncated` when shortened
- `refresh=true` refreshes connector-owned presentation metadata before returning;
  it does not re-fetch stale source content
