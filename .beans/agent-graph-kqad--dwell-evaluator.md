---
# agent-graph-kqad
title: Dwell evaluator
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:19:44Z
updated_at: 2026-03-24T11:06:20Z
parent: agent-graph-dy5s
blocked_by:
    - agent-graph-hpnd
---

Background loop (every 1s). Scans observations for focus events older than N seconds (default 5s) with no matching blur. Emits dwell_detected event → source router. Marks evaluated focus events so they don't re-trigger. Configurable dwell threshold.

## Summary of Changes

- server/dwell.py: evaluate_once() queries for mature focus events with no matching blur
- Dispatches connector fetch via asyncio.create_task (fire-and-forget)
- run_dwell_loop(): background asyncio task polling on dwell_poll_interval_seconds
