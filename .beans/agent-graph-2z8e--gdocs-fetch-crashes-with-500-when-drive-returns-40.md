---
# agent-graph-2z8e
title: gdocs fetch crashes with 500 when Drive returns 404
status: completed
type: bug
priority: normal
created_at: 2026-03-29T11:18:15Z
updated_at: 2026-03-29T11:20:54Z
---

agentgraph fetch gdocs <id> raises a 500 when the Google Drive API returns a 404 (file not found or no access). The HttpError is not caught so it becomes an unhandled server error.

## Summary of Changes

- : catch  from Google Drive API in ; re-raise 404s as  with a descriptive message, let other status codes propagate
- : catch  in  so 4xx/5xx server responses print the error detail instead of crashing with a traceback
