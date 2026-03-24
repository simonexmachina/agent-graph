---
# agent-graph-wr0t
title: CLI query interface
status: todo
type: task
created_at: 2026-03-24T10:50:54Z
updated_at: 2026-03-24T10:50:54Z
parent: agent-graph-414r
blocked_by:
    - agent-graph-k1ub
---

Expose graph exploration as CLI commands mirroring the MCP tools. Commands: agentgraph search <query> [--type ...] [--limit N], agentgraph get <entity-id>, agentgraph edges <entity-id> [--type ...] [--direction in|out|both], agentgraph traverse <entity-id> [--depth N], agentgraph query --type <entity-type> [--filter key=value]. Output as formatted table by default, JSON with --json flag. Reuses the same query layer as MCP — thin CLI wrapper over shared graph functions.
