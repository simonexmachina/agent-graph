+++
title = "connectors"
description = "CLI reference for agentgraph connectors."
nav_title = "connectors"
section = "Reference"
order = 19
summary = "`agentgraph connectors` is the operator view of installed connectors, auth state, URL ownership, and sync behavior."
output = "commands/connectors.html"
source_path = "docs-src/commands/connectors.md"
+++

## Synopsis

```bash
agentgraph connectors [--json]
agentgraph connector <source> <command> [args...] [--json]
```

## Example

```bash
agentgraph connectors
agentgraph connectors --json
agentgraph connector rss add https://simonwillison.net/atom/everything/
agentgraph connector rss import-opml feeds.opml --all
agentgraph connector rss import-opml feeds.opml --select 1,3-5
```

For RSS OPML imports, omit `--all` and `--select` in an interactive terminal to review the
feeds and choose whether to add all feeds or only selected feed numbers.
