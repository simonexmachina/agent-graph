+++
title = "edges"
description = "CLI reference for agentgraph edges."
nav_title = "edges"
section = "Reference"
order = 14
summary = "`agentgraph edges` shows direct graph relationships around one entity without traversing multiple hops."
output = "commands/edges.html"
source_path = "docs-src/commands/edges.md"
+++

## Synopsis

```bash
agentgraph edges ENTITY_ID [--type EDGE_TYPE] [--direction in|out|both] [--json]
```

## Examples

```bash
agentgraph edges abc123ef --direction both
agentgraph edges abc123ef --type authored --direction in --json
```
