---
# agent-graph-kqad
title: Dwell evaluator
status: todo
type: task
created_at: 2026-03-24T10:19:44Z
updated_at: 2026-03-24T10:19:44Z
parent: agent-graph-dy5s
blocked_by:
    - agent-graph-hpnd
---

Background loop (every 1s). Scans observations for focus events older than N seconds (default 5s) with no matching blur. Emits dwell_detected event → source router. Marks evaluated focus events so they don't re-trigger. Configurable dwell threshold.
