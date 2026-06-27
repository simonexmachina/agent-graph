+++
title = "auth"
description = "CLI reference for agentgraph auth."
nav_title = "auth"
section = "Reference"
order = 23
summary = "`agentgraph auth` authenticates credential-backed connector platforms directly, including non-interactive Slack token/cookie input when needed."
output = "commands/auth.html"
source_path = "docs-src/commands/auth.md"
+++

## Synopsis

```bash
agentgraph auth PLATFORM [--xoxc-token TOKEN] [--d-cookie VALUE]
```

## Notes

- `PLATFORM` is the auth label, such as `google`, `slack`, or `discord`
- for Slack, `--xoxc-token` and `--d-cookie` skip the interactive prompt
- RSS and generic web are not authentication providers; configure RSS with `agentgraph connector rss add`

## Examples

```bash
agentgraph auth google
agentgraph auth slack --xoxc-token "$XOXC" --d-cookie "$D_COOKIE"
agentgraph connector rss add https://example.com/feed.xml
```
