---
# agent-graph-8x7k
title: Add SharePoint connector
status: completed
type: feature
priority: normal
created_at: 2026-05-04T13:53:27Z
updated_at: 2026-05-04T13:57:15Z
---

## Summary of Changes

- Added `MicrosoftCredentials` model to `agentgraph/auth/credentials.py`
- Created `agentgraph/auth/microsoft.py` — Microsoft OAuth2 browser flow + token refresh
- Added `agentgraph auth microsoft` CLI command to `agentgraph/cli.py`
- Added SharePoint URL pattern to `agentgraph/server/router.py` — encodes sharing URLs as `u!<base64url>` (Graph API format)
- Created `packages/agentgraph-connector-sharepoint/` package with `SharePointConnector`:
  - Fetches document metadata and content via Microsoft Graph API `/shares/{encoded}` endpoint
  - Extracts text from .docx files using `python-docx`
  - Creates `authored` / `collaborated` edges for document creators/editors
  - Calls `add_stubs_from()` to follow any links in document content
- Added `sharepoint` optional dep to root `pyproject.toml`
- Updated `.claude/skills/graph/SKILL.md` with new auth commands
