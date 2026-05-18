+++
title = "migrate"
description = "CLI reference for agentgraph migrate."
nav_title = "migrate"
section = "Reference"
order = 27
summary = "`agentgraph migrate` copies entities and cursors between backends when you need to move from one persistence layer to another."
output = "commands/migrate.html"
source_path = "docs-src/commands/migrate.md"
+++

## Synopsis

```bash
agentgraph migrate [--from BACKEND] [--to BACKEND]
```

## Notes

- embeddings are recomputed
- edges are not migrated and will be rebuilt on later sync

## Example

```bash
agentgraph migrate --from postgres --to sqlite
```
