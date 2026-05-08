---
# agent-graph-svah
title: Add SharePoint connector
status: in-progress
type: feature
created_at: 2026-05-04T13:53:25Z
updated_at: 2026-05-04T13:53:25Z
---

Implement a SharePoint/OneDrive connector for agentgraph so that sharepoint.com links found in emails and other sources are fetched and added to the knowledge graph.

## Plan
- [ ] Add `MicrosoftCredentials` to `agentgraph/auth/credentials.py`
- [ ] Create `agentgraph/auth/microsoft.py` — OAuth2 browser flow for Microsoft identity platform
- [ ] Add `auth microsoft` CLI command to `agentgraph/cli.py`
- [ ] Add SharePoint URL pattern to `agentgraph/server/router.py`
- [ ] Create `packages/agentgraph-connector-sharepoint/` package
- [ ] Add sharepoint to root `pyproject.toml` optional deps
- [ ] Update `.claude/skills/graph/SKILL.md` with new auth command
