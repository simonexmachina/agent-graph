---
# agent-graph-czb3
title: Person entities missing content_embedding — don't surface in search
status: in-progress
type: bug
created_at: 2026-03-28T13:05:23Z
updated_at: 2026-03-28T13:05:23Z
---

Person entities are inserted without content_embedding in _upsert_persons(). This means they can only rank via fulltext, where they score low (ts_rank is based on term frequency — a thread mentioning someone many times outranks the Person entity with just a short title). Fix: compute embedding in _upsert_persons() and backfill existing persons.
