+++
title = "download"
description = "CLI reference for agentgraph download."
nav_title = "download"
section = "Reference"
order = 18
summary = "`agentgraph download` uses connector auth to fetch the source file for a graph entity, such as a Drive PDF or exported document."
output = "commands/download.html"
source_path = "docs-src/commands/download.md"
+++

## Synopsis

```bash
agentgraph download ENTITY_ID [--output PATH] [--json]
```

## Use it for

- retrieving the current bytes behind a file-backed entity
- writing to a specific file path or directory
- returning download metadata as JSON

## Example

```bash
agentgraph download abc123ef --output ./downloads/
agentgraph download gdrive/19ccFHOXCcr4s62HJb3Eih3JqAd2xIZDq --json
```
