+++
title = "download_entity_tool"
description = "MCP reference for download_entity_tool."
nav_title = "download_entity_tool"
section = "MCP"
order = 21
summary = "Use `download_entity_tool` when the agent needs the source bytes behind a file-backed entity rather than only the indexed graph content."
output = "mcp/download-entity.html"
source_path = "docs-src/mcp/download-entity.md"
+++

## Signature

```text
download_entity_tool(entity_id, output_path=None) -> JSON string
```

## Returns

- local file path
- byte count
- filename
- platform
- MIME type
