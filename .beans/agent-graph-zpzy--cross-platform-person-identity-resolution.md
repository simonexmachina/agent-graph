---
# agent-graph-zpzy
title: Cross-platform person identity resolution
status: in-progress
type: task
priority: normal
created_at: 2026-03-24T10:20:17Z
updated_at: 2026-03-24T11:06:29Z
parent: agent-graph-af03
blocked_by:
    - agent-graph-hpnd
---

When ingesting a new person: look up canonical_email in persons table. If found, add platform_identity row linking to existing person. If not found, create new person + identity. Handle email-less identities (Slack user IDs without email) as platform-scoped persons until email is known.
