+++
title = "auth"
description = "CLI reference for agentgraph auth."
nav_title = "auth"
section = "Reference"
order = 23
summary = "`agentgraph auth` authenticates and removes credential-backed connector platforms directly, including non-interactive Slack token/cookie input when needed."
output = "commands/auth.html"
source_path = "docs-src/commands/auth.md"
+++

## Synopsis

```bash
agentgraph auth PLATFORM [--account ACCOUNT_ID] [--add] [PROVIDER_OPTIONS]
agentgraph auth remove PLATFORM [--account ACCOUNT_ID] [--json]
```

## Notes

- `PLATFORM` is the auth label, such as `google`, `slack`, or `discord`
- Google uses AgentGraph's packaged Desktop OAuth client
- for Slack, `--xoxc-token` and `--d-cookie` skip the interactive prompt
- `agentgraph auth remove PLATFORM` removes stored credentials for that provider; it does not delete indexed graph data
- `--account` removes one stored account for multi-account providers
- RSS and generic web are not authentication providers; configure RSS with `agentgraph connector rss add`

## Examples

```bash
agentgraph auth google
agentgraph auth slack --xoxc-token "$XOXC" --d-cookie "$D_COOKIE"
agentgraph auth remove slack
agentgraph auth remove google --account user@example.com --json
agentgraph connector rss add https://example.com/feed.xml
```
