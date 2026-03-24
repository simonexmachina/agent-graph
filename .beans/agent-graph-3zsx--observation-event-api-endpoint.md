---
# agent-graph-3zsx
title: Observation event API endpoint
status: in-progress
type: task
priority: normal
created_at: 2026-03-24T10:19:43Z
updated_at: 2026-03-24T11:02:06Z
parent: agent-graph-dy5s
blocked_by:
    - agent-graph-k0ya
---

POST /observe — accepts FocusEvent and BlurEvent from browser extension. Persists to a observations table (url, type, tab_id, timestamp). Returns 200 immediately. Validate against known URL patterns only if source toggles are respected.
