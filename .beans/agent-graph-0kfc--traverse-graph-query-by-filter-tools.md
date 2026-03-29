---
# agent-graph-0kfc
title: traverse_graph + query_by_filter tools
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:20:28Z
updated_at: 2026-03-24T11:23:06Z
parent: agent-graph-414r
blocked_by:
    - agent-graph-k1ub
---

traverse_graph(start_id, edge_types?, max_depth=2): BFS/DFS multi-hop traversal via recursive SQL CTE. Returns subgraph as nodes+edges. Update last_accessed on all visited entities. query_by_filter(entity_type, filters, limit=50): structured filter query (platform, date range, person, keyword).
