+++
title = "mcp-serve"
description = "CLI reference for agentgraph mcp-serve."
nav_title = "mcp-serve"
section = "Reference"
order = 26
summary = "`agentgraph mcp-serve` runs the MCP server directly, either over stdio or over remote transports for external clients."
output = "commands/mcp-serve.html"
source_path = "docs-src/commands/mcp-serve.md"
+++

## Synopsis

```bash
agentgraph mcp-serve [--transport stdio|sse|streamable-http] [--host HOST] [--port PORT]
```

## Examples

```bash
agentgraph mcp-serve
agentgraph mcp-serve --transport sse --port 8808
agentgraph mcp-serve --transport streamable-http --host 0.0.0.0 --port 8808
```
