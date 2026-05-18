+++
title = "get"
description = "CLI reference for agentgraph get."
nav_title = "get"
section = "Reference"
order = 13
summary = "`agentgraph get` returns one entity in full, either directly from the graph or by resolving a stub from the source connector."
output = "commands/get.html"
source_path = "docs-src/commands/get.md"
+++

## Synopsis

```bash
agentgraph get ENTITY_ID [--resolve] [--json]
```

## Use it for

- inspecting one known entity from a search result
- resolving a stub entity into full content
- retrieving one record as JSON

## Examples

```bash
agentgraph get abc123ef
agentgraph get slack/C04TT9U6B --resolve --json
```
