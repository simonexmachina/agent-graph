+++
title = "traverse"
description = "CLI reference for agentgraph traverse."
nav_title = "traverse"
section = "Reference"
order = 15
summary = "`agentgraph traverse` walks outward from one entity to build a local subgraph around it."
output = "commands/traverse.html"
source_path = "docs-src/commands/traverse.md"
+++

## Synopsis

```bash
agentgraph traverse ENTITY_ID [--depth N] [--resolve] [--json]
```

## Examples

```bash
agentgraph traverse abc123ef --depth 2
agentgraph traverse abc123ef --depth 3 --resolve --json
agentgraph traverse abc123ef --depth 0 --json
```

`--depth 0` returns only the starting entity. Depths 1 through 4 include that many relationship hops.
