+++
title = "get"
description = "CLI reference for agentgraph get."
nav_title = "get"
section = "Reference"
order = 13
summary = "`agentgraph get` returns one existing entity in full by ID, platform reference, or URL."
output = "commands/get.html"
source_path = "docs-src/commands/get.md"
+++

## Synopsis

```bash
agentgraph get TARGET [--resolve] [--json]
```

## Use it for

- inspecting one known entity from a search result
- looking up an already-indexed entity by URL
- resolving a stub entity into full content
- retrieving one record as JSON

## Examples

```bash
agentgraph get abc123ef
agentgraph get slack/C04TT9U6B --resolve --json
agentgraph get https://example.com/page --json
```
