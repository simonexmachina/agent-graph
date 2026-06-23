+++
title = "query"
description = "CLI reference for agentgraph query."
nav_title = "query"
section = "Reference"
order = 12
summary = "`agentgraph query` is the structured alternative to search: pick an entity type, add filters, and sort the result set directly."
output = "commands/query.html"
source_path = "docs-src/commands/query.md"
+++

## Synopsis

```bash
agentgraph query --type TYPE [--filter key=value] [--since 24h] [--mine] [--has-attachments] [--limit N] [--order-by FIELD] [--json]
```

## Use it for

- listing recent messages in one source
- finding your own authored entities
- finding message entities that contain uploaded files or images
- listing Gmail attachment `Document` stubs referenced by email threads

## Key arguments

- `--type` - required entity type
- `--filter` - repeatable `key=value` filter against columns or metadata
- `--since` - ISO timestamp or relative duration such as `12h`, `30m`, `2d`
- `--mine` - only entities authored by the authenticated user
- `--has-attachments` - only `Message` entities with chat-style attachments; Gmail email attachments are `Document` stubs

## Examples

```bash
agentgraph query --type Message --filter platform=slack --since 24h --limit 20
agentgraph query --type Message --has-attachments --since 7d --json
agentgraph query --type Document --filter platform=gmail --json
```
