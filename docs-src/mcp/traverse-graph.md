+++
title = "traverse_graph_tool"
description = "MCP reference for traverse_graph_tool."
nav_title = "traverse_graph_tool"
section = "MCP"
order = 18
summary = "Use `traverse_graph_tool` to build a bounded local graph around one entity when direct search results are not enough."
output = "mcp/traverse-graph.html"
source_path = "docs-src/mcp/traverse-graph.md"
+++

## Signature

```text
traverse_graph_tool(entity_id, max_depth=2) -> JSON string
```

## Note

- depth is clamped between 1 and 4
