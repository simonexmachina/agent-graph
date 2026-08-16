+++
title = "get_edges_tool"
description = "MCP reference for get_edges_tool."
nav_title = "get_edges_tool"
section = "MCP"
order = 17
summary = "Use `get_edges_tool` to inspect direct authored, replied-to, mentions, and similar graph relationships around one entity."
output = "mcp/get-edges.html"
source_path = "docs-src/mcp/get-edges.md"
+++

## Signature

```text
get_edges_tool(entity_id, edge_type=null, direction="both") -> JSON string
```

`entity_id` accepts a full UUID, unambiguous UUID prefix, or platform reference. The
tool resolves that target to the canonical internal UUID before listing incoming,
outgoing, or both edge directions.
