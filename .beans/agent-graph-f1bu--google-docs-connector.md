---
# agent-graph-f1bu
title: Google Docs connector
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:20:05Z
updated_at: 2026-03-24T11:15:41Z
parent: agent-graph-sb7y
blocked_by:
    - agent-graph-hpnd
---

On dwell: fetch doc via documents.get. Extract: title, plain text content, headings, comments, collaborators. Produce Document entity + Person entities for collaborators + authored/collaborated edges. OAuth2 user token — acquired via CLI onboarding flow (see auth onboarding task). Store token + refresh token locally. Rate limit: 300 reads/min per user.
