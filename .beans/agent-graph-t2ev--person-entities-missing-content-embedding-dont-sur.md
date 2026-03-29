---
# agent-graph-t2ev
title: Person entities missing content_embedding — don't surface in search
status: completed
type: bug
priority: normal
created_at: 2026-03-28T13:05:27Z
updated_at: 2026-03-28T13:13:27Z
---

Person entities are inserted without content_embedding in _upsert_persons(). Fix: compute embedding in _upsert_persons() and backfill existing persons.

## Summary of Changes

- Added embedding computation to `_upsert_persons()` (text = display_name + canonical_email)
- Backfilled 1001 existing Person entities with NULL content_embedding
- Fixed ivfflat approximate search: added `SET ivfflat.probes = 10` in `search_entities()` — default probes=1 was only scanning ~1% of the index, causing genuine rank-6 results to be missed
- Three-way root cause: (1) no embedding → (2) fulltext-only score 0.028 below min_score 0.03 → (3) probe count too low for index to find Person even after backfill
