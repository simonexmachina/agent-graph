+++
title = "download"
description = "CLI reference for agentgraph download."
nav_title = "download"
section = "Reference"
order = 18
summary = "`agentgraph download` uses connector auth to fetch the source file for a graph entity, such as a Drive PDF, exported document, or Gmail attachment stub."
output = "commands/download.html"
source_path = "docs-src/commands/download.md"
+++

## Synopsis

```bash
agentgraph download ENTITY_ID [--output PATH] [--json]
```

## Use it for

- retrieving the current bytes behind a file-backed entity
- downloading Gmail attachments after they have been indexed as `Document` stubs
- writing to a specific file path or directory
- returning download metadata as JSON

## Example

```bash
agentgraph download abc123ef --output ./downloads/
agentgraph download gdrive/19ccFHOXCcr4s62HJb3Eih3JqAd2xIZDq --json
agentgraph download 'gmail/document/attachment/<message-id>/<attachment-id>' --output .
```

For Gmail, run `agentgraph fetch-entity <thread-id>` and then
`agentgraph traverse <thread-id> --depth 1 --json` to discover the attachment
`Document` stubs referenced by the thread.
