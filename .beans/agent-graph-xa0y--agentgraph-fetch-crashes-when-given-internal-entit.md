---
# agent-graph-xa0y
title: agentgraph fetch crashes when given internal entity UUID instead of platform_entity_id
status: completed
type: bug
priority: normal
created_at: 2026-03-29T11:28:32Z
updated_at: 2026-03-29T11:33:26Z
---

fetch_entity only queries by platform_entity_id. If you pass an internal UUID (the id column), it finds nothing, resets synced_at on nothing, then passes the UUID directly to Google Drive which returns a 404. Should resolve internal UUIDs to platform_entity_id automatically.

## Summary of Changes

- : after the initial platform_entity_id lookup, if no row is found, retry the query matching the given ID against the internal UUID column (id::text). Updates resource_id to the resolved platform_entity_id before proceeding.
- Also added pyright suppression comments to suppress pre-existing asyncpg untyped warnings.

## Revised approach\n\nActually reverted the UUID resolution from fetch_entity. Instead, added a dedicated fetch-entity command and fetch_entity_by_id function.
