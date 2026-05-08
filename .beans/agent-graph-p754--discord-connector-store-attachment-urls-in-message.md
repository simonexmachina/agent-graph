---
# agent-graph-p754
title: 'Discord connector: store attachment URLs in message metadata'
status: completed
type: bug
priority: normal
created_at: 2026-05-04T14:26:25Z
updated_at: 2026-05-04T14:27:20Z
---

The Discord connector discards attachment data from the message payload. Store image/file attachment URLs in message metadata so they can be surfaced in the viewer.

## Summary of Changes

Added  helper that pulls , , , , and  from the Discord API attachment payload. Applied in both  and  — attachments are stored under  on the message entity. Attachments without a URL are skipped; optional fields omitted when absent. Existing messages won't have the data until re-fetched.
