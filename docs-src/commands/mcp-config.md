+++
title = "mcp-config"
description = "CLI reference for agentgraph mcp-config."
nav_title = "mcp-config"
section = "Reference"
order = 25
summary = "`agentgraph mcp-config` prints the MCP client snippet for stdio clients and the HTTPS `/mcp` setup path for ChatGPT developer mode."
output = "commands/mcp-config.html"
source_path = "docs-src/commands/mcp-config.md"
+++

## Synopsis

```bash
agentgraph mcp-config
```

## Use it for

- Claude Desktop config
- Claude Code config
- ChatGPT developer mode guidance for a remote HTTPS streamable HTTP endpoint

## Example

```bash
agentgraph mcp-config
```

For ChatGPT, do not paste the stdio JSON config. Run AgentGraph with streamable HTTP instead:

```bash
agentgraph mcp-serve --transport streamable-http --port 8808
```

The local endpoint is:

```text
http://127.0.0.1:8808/mcp
```

ChatGPT cannot connect to that local URL directly. Expose it through Secure MCP Tunnel, ngrok, Cloudflare Tunnel, or another HTTPS tunnel, then create an app/connector in ChatGPT developer mode using the public URL ending in `/mcp`.
