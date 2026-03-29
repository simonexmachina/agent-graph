---
# agent-graph-nbqz
title: Connector interface + refresh policy
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:20:05Z
updated_at: 2026-03-24T11:10:22Z
parent: agent-graph-sb7y
---

Define SourceConnector protocol: canHandle(url), parseUrl(url) → ResourceRef, fetch(ref) → EntityBatch. Implement refresh policy: first visit → full fetch with padding; stale (>threshold) → incremental fetch; fresh → update last_accessed only. Staleness: Google Docs 15min, Slack 5min.

## Summary of Changes

Implemented in commit 89db2d4. See graph/upsert.py, graph/gc.py, connectors/base.py.
