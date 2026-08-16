+++
title = "demo"
description = "CLI reference for creating the self-contained AgentGraph demo graph."
nav_title = "demo"
section = "Reference"
order = 29
summary = "`agentgraph demo seed` creates the fictional graph used by the reproducible cross-source demonstration."
output = "commands/demo.html"
source_path = "docs-src/commands/demo.md"
+++

## Synopsis

```bash
agentgraph demo seed --config-dir DIRECTORY [--reset] [--json]
```

The seed command is offline and refuses the default `~/.agentgraph` directory. It
also refuses to replace an existing demo database unless `--reset` is supplied and
will not overwrite a non-demo `.env` file.

See [Trace a decision](/demo.html) for the complete workflow and expected evidence.
