---
# agent-graph-atec
title: Layered architecture refactor
status: in-progress
type: feature
priority: high
created_at: 2026-04-29T13:34:48Z
updated_at: 2026-04-29T21:49:25Z
---

Separate agentgraph into clean layers: StorageBackend ABC, pluggable backends (SQLite default, PostgreSQL), connector entry-point ecosystem, thin CLI/MCP commands.

## Phases
- [x] Phase 1: StorageBackend ABC + PostgresBackend (delete agentgraph/db/)
- [x] Phase 2: SQLite backend + in-memory test support + migrate command
- [x] Phase 3: Connector entry-point discovery
- [x] Phase 4: Move built-in connectors to packages/agentgraph-connector-*/
- [ ] Phase 5: Design-only for neo4j-memory + MemPalace (future)
