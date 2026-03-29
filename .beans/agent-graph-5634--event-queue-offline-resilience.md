---
# agent-graph-5634
title: Event queue + offline resilience
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:19:19Z
updated_at: 2026-03-24T11:18:02Z
parent: agent-graph-4q2a
blocked_by:
    - agent-graph-hpnd
---

lib/event-queue.js: batch focus events (2s), flush blur immediately. If localhost endpoint is unreachable, queue in memory (max 500 events). On reconnection, flush in order. Exponential backoff on retry.
