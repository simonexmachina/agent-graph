---
# agent-graph-5mw3
title: Source router (URL → connector dispatch)
status: todo
type: task
priority: normal
created_at: 2026-03-24T10:19:44Z
updated_at: 2026-03-24T10:35:27Z
parent: agent-graph-dy5s
---

classifyUrl(url) → SourceReference {source, resourceType, resourceId} or null. Pattern rules for: Google Docs (docs.google.com/document/d/{id}), Slack (app.slack.com/client/{workspace}/{channel}). Dispatches to registered connector. Easy to extend with new URL patterns.
