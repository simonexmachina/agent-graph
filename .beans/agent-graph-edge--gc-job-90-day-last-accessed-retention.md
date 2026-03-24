---
# agent-graph-edge
title: 'GC job: 90-day last_accessed retention'
status: todo
type: task
created_at: 2026-03-24T10:20:17Z
updated_at: 2026-03-24T10:20:17Z
parent: agent-graph-af03
blocked_by:
    - agent-graph-hpnd
---

Scheduled job (daily via APScheduler or pg_cron). DELETE FROM entities WHERE last_accessed < now() - INTERVAL '90 days'. Edges removed via ON DELETE CASCADE. Person entities skipped if they still have edges. Log how many rows were pruned each run. Configurable retention period.
