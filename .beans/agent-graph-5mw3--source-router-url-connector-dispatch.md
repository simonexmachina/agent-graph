---
# agent-graph-5mw3
title: Source router (URL → connector dispatch)
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:19:44Z
updated_at: 2026-03-24T11:06:20Z
parent: agent-graph-dy5s
---

classifyUrl(url) → SourceReference {source, resourceType, resourceId} or null. Pattern rules for: Google Docs (docs.google.com/document/d/{id}), Slack (app.slack.com/client/{workspace}/{channel}). Dispatches to registered connector. Easy to extend with new URL patterns.

## Summary of Changes

- server/router.py: classify_url() with regex patterns for gdocs and slack
- Returns typed SourceReference(source, resource_type, resource_id) or None
- 7 parametrized test cases covering both sources + unrecognised URLs
