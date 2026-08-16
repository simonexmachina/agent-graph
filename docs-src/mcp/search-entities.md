+++
title = "search_entities_tool"
description = "MCP reference for search_entities_tool."
nav_title = "search_entities_tool"
section = "MCP"
order = 15
summary = "Use `search_entities_tool` for broad discovery from natural-language questions, especially before drilling into one entity."
output = "mcp/search-entities.html"
source_path = "docs-src/mcp/search-entities.md"
+++

## Signature

```text
search_entities_tool(query, entity_types=null, platform=null, limit=10, min_score=0.03, refresh=false) -> JSON string
```

## Notes

- for images and uploaded files, search `Message` entities rather than `Document`
- results contain bounded content snippets and set `content_truncated` when shortened;
  use `get_entity_tool` for full stored content
- `refresh=true` allows connector-owned presentation metadata, such as temporary
  attachment URLs, to be refreshed before returning; it does not replace a targeted
  source fetch for stale content
