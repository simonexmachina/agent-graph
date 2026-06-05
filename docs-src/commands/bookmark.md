+++
title = "bookmark"
description = "CLI reference for agentgraph bookmark."
nav_title = "bookmark"
section = "Reference"
order = 19
summary = "`agentgraph bookmark` marks an entity so garbage collection will not remove it, even after the retention window."
output = "commands/bookmark.html"
source_path = "docs-src/commands/bookmark.md"
+++

## Synopsis

```bash
agentgraph bookmark ENTITY_ID [--json]
```

## Use it for

- preserving an entity that should survive retention-window garbage collection
- protecting useful search results before old data is pruned
- returning the updated entity as JSON

## Examples

```bash
agentgraph bookmark abc123ef
agentgraph bookmark gdrive/19ccFHOXCcr4s62HJb3Eih3JqAd2xIZDq --json
```
