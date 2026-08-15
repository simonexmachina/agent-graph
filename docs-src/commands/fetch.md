+++
title = "fetch"
description = "CLI reference for agentgraph fetch."
nav_title = "fetch"
section = "Reference"
order = 16
summary = "`agentgraph fetch` asks one connector to ingest a platform entity immediately by its platform-specific ID."
output = "commands/fetch.html"
source_path = "docs-src/commands/fetch.md"
+++

## Synopsis

```bash
agentgraph fetch PLATFORM RESOURCE_ID [--json]
```

Use targeted fetch when a search result, graph edge, or external reference identifies context that is missing or stale. The owning connector persists its complete returned batch before the command reports counts.

Direct fetch does not update `observed_at`; it is source retrieval, not evidence that the human viewed the resource.

## Examples

```bash
agentgraph fetch slack C0J2L41FT
agentgraph fetch gdocs 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms --json
```
