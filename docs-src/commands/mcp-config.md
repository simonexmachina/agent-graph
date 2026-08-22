+++
title = "mcp-config"
description = "CLI reference for agentgraph mcp-config."
nav_title = "mcp-config"
section = "Reference"
order = 25
summary = "`agentgraph mcp-config` prints local stdio setup instructions for ChatGPT Desktop Work Mode and Claude Desktop."
output = "commands/mcp-config.html"
source_path = "docs-src/commands/mcp-config.md"
+++

## Synopsis

```bash
agentgraph mcp-config
```

## Use it for

- ChatGPT Desktop Work Mode local MCP setup
- Claude Desktop config

## Example

```bash
agentgraph mcp-config
```

For ChatGPT Desktop Work Mode, add a local MCP server in the MCP configuration screen. Enter the printed `agentgraph` executable in **Command to launch** and `mcp-serve` in **Arguments**.

For Claude Desktop, add the printed JSON to `~/Library/Application Support/Claude/claude_desktop_config.json`.
