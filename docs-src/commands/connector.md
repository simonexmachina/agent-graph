+++
title = "connector"
description = "CLI reference for connector-owned AgentGraph commands."
nav_title = "connector"
section = "Reference"
order = 19
summary = "`agentgraph connector` discovers and runs commands implemented by an installed connector without adding source-specific branches to the core CLI."
output = "commands/connector.html"
source_path = "docs-src/commands/connector.md"
+++

## Synopsis

```bash
agentgraph connector SOURCE --help
agentgraph connector SOURCE COMMAND [ARGS...] [--json]
```

Connector names and command sets are dynamic. Inspect `agentgraph list-connectors`, then
use connector-owned help rather than assuming a fixed platform or command list.

## Examples

```bash
agentgraph connector rss --help
agentgraph connector rss add https://example.com/feed.xml
agentgraph connector gmail ingest --account user@example.com --json
```

Historical ingest is connector-owned. There is no top-level `agentgraph ingest`
command. Gmail currently exposes an optional 90-day backfill through its connector
command; omit `--account` to queue it for every authenticated Google account. Commands
that queue a poll or ingest send that work to the running local AgentGraph server.
