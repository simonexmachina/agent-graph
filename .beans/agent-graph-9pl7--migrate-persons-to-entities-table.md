---
# agent-graph-9pl7
title: Migrate persons to entities table
status: completed
type: task
priority: normal
created_at: 2026-03-27T09:46:58Z
updated_at: 2026-03-27T09:54:49Z
---

Store Person nodes as entities (entity_type='Person', platform='canonical', platform_entity_id=email) instead of a separate persons table. Simplifies the schema by removing persons, platform_identities tables and person_id columns from edges.

## Summary of Changes

- Removed persons and platform_identities tables from schema
- Person nodes are now entities with entity_type='Person', platform='canonical', platform_entity_id=email
- Added migrate_v2.sql: migrates existing persons to entities, updates edges, drops old columns/tables
- upsert.py: _upsert_persons writes to entities table; _upsert_edges uses only entity IDs
- query.py: get_edges, traverse_graph, query_by_filter all simplified (no person ID handling)
- graph_api.py: removed _person_to_node, _fetch_person_nodes_for_entities; Person filter now works natively
- gc.py: removed separate persons GC (now just entities)
- cli_query.py: removed source_person_id/target_person_id edge display
- viewer.html: removed person: prefix handling in edge detail panel
- All tests updated to reflect new schema
