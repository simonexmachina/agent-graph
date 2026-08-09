+++
title = "auth"
description = "CLI reference for agentgraph auth."
nav_title = "auth"
section = "Reference"
order = 23
summary = "`agentgraph auth` authenticates and removes credential-backed connector platforms directly. Slack uses user OAuth PKCE by default with an explicit browser-session fallback."
output = "commands/auth.html"
source_path = "docs-src/commands/auth.md"
+++

## Synopsis

```bash
agentgraph auth PLATFORM [--add] [--account ACCOUNT_ID]
agentgraph auth slack [--method oauth|browser] [--xoxc-token TOKEN] [--d-cookie VALUE]
agentgraph auth remove PLATFORM [--account ACCOUNT_ID] [--json]
```

## Notes

- `PLATFORM` is the auth label, such as `google`, `slack`, or `discord`
- Slack defaults to `--method oauth`; browser credential options imply `--method browser`
- `--xoxc-token` and `--d-cookie` are rejected with explicit `--method oauth`
- status account rows include `auth_method`
- `agentgraph auth remove PLATFORM` removes stored credentials for that provider; it does not delete indexed graph data
- `--account` removes one stored account for multi-account providers
- RSS and generic web are not authentication providers; configure RSS with `agentgraph connector rss add`

## Examples

```bash
agentgraph auth google
agentgraph auth slack
agentgraph auth slack --method browser --xoxc-token "$XOXC" --d-cookie "$D_COOKIE"
agentgraph auth remove slack
agentgraph auth remove google --account user@example.com --json
agentgraph connector rss add https://example.com/feed.xml
```
