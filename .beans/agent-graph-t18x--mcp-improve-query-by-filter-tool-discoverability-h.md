---
# agent-graph-t18x
title: 'MCP: improve query_by_filter_tool discoverability + has_attachments filter'
status: completed
type: task
priority: normal
created_at: 2026-05-04T14:59:02Z
updated_at: 2026-05-04T15:03:28Z
---

Improve tool docstrings to communicate entity type contents (especially images on Message), add has_attachments filter to query_by_filter_tool.

## Summary of Changes

- : added prominent note that images/attachments are on Message entities, not Documents
- : expanded entity_type docs listing what each type contains, added worked example, added has_attachments param
-  filter threaded through: StorageBackend ABC → graph/query.py → SQLite backend → Postgres backend → server CLI API → cli_query.py → CLI (--has-attachments flag)
- SKILL.md updated with entity type table and --has-attachments flag
