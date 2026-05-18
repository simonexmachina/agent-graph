+++
title = "search"
description = "CLI reference for agentgraph search."
nav_title = "search"
section = "Reference"
order = 11
summary = "`agentgraph search` is the fastest path when you have a user question or keyword and need likely matches across the local graph."
output = "commands/search.html"
source_path = "docs-src/commands/search.md"
+++

## Synopsis

```bash
agentgraph search QUERY [--type TYPE] [--platform PLATFORM] [--limit N] [--min-score SCORE] [--json]
```

## Use it for

- broad discovery from natural-language text
- narrowing results to one entity type or platform
- returning machine-readable results with `--json`

## Key arguments

- `QUERY` - free-text query
- `--type` - repeatable entity type filter such as `Message` or `Document`
- `--platform` - source filter such as `slack`, `gmail`, or `gdocs`
- `--min-score` - suppress weak matches

## Examples

```bash
agentgraph search "project kickoff notes" --type Document --limit 10
agentgraph search "images from standup" --type Message --platform slack --json
```
