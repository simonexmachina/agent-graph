---
# agent-graph-wzjf
title: Discord connector rate-limit handling
status: completed
type: bug
priority: normal
created_at: 2026-03-27T11:36:17Z
updated_at: 2026-03-27T11:37:21Z
---

Discord connector hammers /users/{id} endpoint with no rate-limit handling, causing 429 errors. No retry-with-backoff on 429 responses, and user cache is per-fetch only so same users are re-fetched on every sync.

## Summary of Changes

- Added 429 retry loop in  with up to 3 retries, respecting the  header and logging global vs per-route rate limits
- Added module-level  so  lookups persist across fetches — same user won't be re-fetched on subsequent channel syncs
