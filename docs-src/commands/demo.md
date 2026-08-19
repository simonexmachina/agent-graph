+++
title = "demo"
description = "CLI reference for adding and removing the self-contained AgentGraph demo graph."
nav_title = "demo"
section = "Reference"
order = 29
summary = "`agentgraph demo add` adds the fictional graph used by the reproducible cross-source demonstration."
output = "commands/demo.html"
source_path = "docs-src/commands/demo.md"
+++

## Synopsis

```bash
AGENTGRAPH_CONFIG_DIR=DIRECTORY agentgraph demo add [--json]
AGENTGRAPH_CONFIG_DIR=DIRECTORY agentgraph demo remove [--json]
```

The add command is offline and adds marked Atlas fixtures to the configured database.
The remove command deletes only those marked fixtures and their connected edges. Both
commands use `AGENTGRAPH_CONFIG_DIR` and do not create or modify `.env` files.

See [Trace a decision](/demo.html) for the complete workflow and expected evidence.
