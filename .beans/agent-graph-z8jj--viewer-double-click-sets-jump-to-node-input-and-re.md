---
# agent-graph-z8jj
title: 'Viewer: double-click sets Jump-to-node input and respects type filters'
status: completed
type: bug
priority: normal
created_at: 2026-03-28T11:46:15Z
updated_at: 2026-03-28T11:46:47Z
---

Double-clicking a node in the viewer should: 1) populate the Jump-to-node input with that node's ID, 2) respect the current entity type filter checkboxes. Currently it bypasses the type filter by calling loadGraph without entity_type. Also, the backend traverse_graph path ignores entity_type params entirely.

## Summary of Changes\n\n- ****: Post-filter  results by  when params are provided (center_id path previously ignored type filters)\n- ****: Double-click now populates the Jump-to-node input with the node ID and calls  so current type filter checkboxes are respected\n- ****: Lookup and fetch-refresh also switched to  for consistency
