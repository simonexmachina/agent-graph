---
# agent-graph-kt1s
title: Add AzureCliProvider for Microsoft auth
status: completed
type: task
priority: normal
created_at: 2026-05-04T14:04:03Z
updated_at: 2026-05-04T14:05:47Z
---

## Summary of Changes

- Created `agentgraph/auth/microsoft_provider.py` with `OAuthProvider` and `AzureCliProvider`
- `AzureCliProvider` runs `az account get-access-token` as a subprocess — no app registration needed
- Added `microsoft_auth_provider` setting to `agentgraph/config.py` (default: `az`)
- Updated `SharePointConnector` to call `get_provider().get_access_token()` instead of directly calling the OAuth helper
- Updated CLI help text to mention the `az login` shortcut
- Updated SKILL.md
