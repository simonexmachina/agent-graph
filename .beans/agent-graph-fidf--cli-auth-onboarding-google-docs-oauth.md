---
# agent-graph-fidf
title: 'CLI auth onboarding: Google Docs OAuth + Slack cookies'
status: todo
type: task
priority: normal
created_at: 2026-03-24T10:30:07Z
updated_at: 2026-03-24T10:34:21Z
parent: agent-graph-szbj
---

agentgraph auth google-docs — runs OAuth 2.0 user token flow in the CLI. Opens browser to Google consent screen, handles redirect on localhost callback, stores access_token + refresh_token in local config (~/.agentgraph/credentials.json). Auto-refresh on expiry using refresh_token. Required scopes: drive.readonly, documents.readonly.

## Slack Auth

agentgraph auth slack — guided prompt flow. No redirect needed. Prints step-by-step instructions to open DevTools → Application → Cookies → app.slack.com, then prompts for the xoxc- token value and d cookie value. Stores both in ~/.agentgraph/credentials.json alongside Google credentials.
