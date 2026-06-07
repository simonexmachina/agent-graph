+++
title = "delete"
description = "CLI reference for agentgraph delete."
nav_title = "delete"
section = "Reference"
order = 20
summary = "`agentgraph delete` removes one entity from the graph by ID, platform reference, or URL."
output = "commands/delete.html"
source_path = "docs-src/commands/delete.md"
+++

## Synopsis

```bash
agentgraph delete TARGET [--json]
```

## Use it for

- removing a stale or incorrect graph entity
- deleting by full UUID, UUID prefix, platform reference, or URL
- returning the deleted entity as JSON for confirmation

Connected edges are removed with the entity.

## Examples

```bash
agentgraph delete abc123ef
agentgraph delete gdrive/19ccFHOXCcr4s62HJb3Eih3JqAd2xIZDq --json
agentgraph delete https://example.com/notes.html
```
