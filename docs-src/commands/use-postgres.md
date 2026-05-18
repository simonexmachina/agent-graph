+++
title = "use-postgres"
description = "CLI reference for agentgraph use-postgres."
nav_title = "use-postgres"
section = "Reference"
order = 28
summary = "`agentgraph use-postgres` switches the saved backend config to PostgreSQL and writes compose scaffolding for a local database."
output = "commands/use-postgres.html"
source_path = "docs-src/commands/use-postgres.md"
+++

## Synopsis

```bash
agentgraph use-postgres [--url DATABASE_URL] [--compose-out PATH]
```

## Example

```bash
agentgraph use-postgres
agentgraph use-postgres --compose-out -
```
