---
# agent-graph-cx3x
title: Stub extraction for linked URLs in connector batches
status: completed
type: feature
priority: normal
created_at: 2026-03-29T10:51:37Z
updated_at: 2026-03-29T10:54:44Z
---

When a connector ingests content containing URLs handled by other connectors (e.g. a Google Doc link in an email), it should create stub EntityRecords for those linked resources and include them in the returned EntityBatch. The behaviour should be shared — a single helper on EntityBatch called by all connectors.

- [x] Add _URL_RE, _RESOURCE_TYPE_TO_ENTITY_TYPE, is_stub field, and EntityBatch.add_stubs_from() to base.py
- [x] Handle is_stub entities in upsert.py (preserve synced_at=NULL)
- [x] Import _RESOURCE_TYPE_TO_ENTITY_TYPE from base in link.py (DRY)
- [x] Update all 5 connectors to call batch.add_stubs_from() for content-bearing entities

## Summary of Changes

Added shared stub extraction to the connector layer:
- `EntityBatch.add_stubs_from(entity)` in `base.py`: scans entity content for recognisable URLs via `classify_url`, appends stub `EntityRecord`s (`is_stub=True`) and `references` `EdgeRecord`s to the batch
- `EntityRecord.is_stub: bool = False` field distinguishes placeholders from fully-fetched entities
- `RESOURCE_TYPE_TO_ENTITY_TYPE` moved to `base.py`; `link.py` imports it from there
- `_upsert_entities` in `upsert.py` handles stubs with a minimal INSERT that preserves `synced_at=NULL` (so connectors re-fetch on next visit) and never overwrites existing content on conflict
- All 5 connectors call `batch.add_stubs_from(entity)` at the end of their `_fetch_*` functions
- Also fixed pre-existing test import: `_extract_plain_text` → `_extract_markdown`
