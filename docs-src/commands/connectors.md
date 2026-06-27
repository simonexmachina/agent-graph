+++
title = "connectors"
description = "CLI reference for agentgraph connectors."
nav_title = "connectors"
section = "Reference"
order = 19
summary = "`agentgraph connectors` is the operator view of installed connectors, credential state where applicable, URL ownership, and sync behavior."
output = "commands/connectors.html"
source_path = "docs-src/commands/connectors.md"
+++

## Synopsis

```bash
agentgraph connectors [--json]
agentgraph connector <source> <command> [args...] [--json]
agentgraph connector <source> --help
```

## Example

```bash
agentgraph connectors
agentgraph connectors --json
agentgraph connector rss add https://simonwillison.net/atom/everything/
agentgraph connector rss add https://simonwillison.net/
agentgraph connector rss remove https://simonwillison.net/atom/everything/
agentgraph connector rss --help
agentgraph connector rss import-opml feeds.opml --all
agentgraph connector rss import-opml feeds.opml --select 1,3-5
```

RSS `add` validates each feed before saving. If you pass an HTML page or file,
AgentGraph scans standard RSS/Atom `<link rel="alternate">` tags and adds the
discovered feed URL.

RSS `remove` removes exact configured feed URLs without fetching or validating them.

For RSS OPML imports, omit `--all` and `--select` in an interactive terminal to choose
feeds with a checkbox prompt.

Connectors that do not use credentials, such as RSS and generic web, omit auth
status in the human output and report `null` auth fields in JSON.
