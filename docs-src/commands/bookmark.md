+++
title = "bookmark"
description = "CLI reference for agentgraph bookmark."
nav_title = "bookmark"
section = "Reference"
order = 19
summary = "`agentgraph bookmark` marks an entity or URL so garbage collection will not remove it, even after the retention window."
output = "commands/bookmark.html"
source_path = "docs-src/commands/bookmark.md"
+++

## Synopsis

```bash
agentgraph bookmark TARGET [--remove] [--json]
```

## Use it for

- preserving an entity that should survive retention-window garbage collection
- retrieving and preserving an HTTP(S) URL
- removing bookmark protection from an existing entity
- protecting useful search results before old data is pruned
- returning the updated entity as JSON

## Examples

```bash
agentgraph bookmark abc123ef
agentgraph bookmark gdrive/19ccFHOXCcr4s62HJb3Eih3JqAd2xIZDq --json
agentgraph bookmark https://example.com/notes.html
agentgraph bookmark abc123ef --remove
```
