---
# agent-graph-hpnd
title: PostgreSQL schema + pgvector setup
status: in-progress
type: task
priority: normal
created_at: 2026-03-24T10:18:53Z
updated_at: 2026-03-24T10:54:00Z
parent: agent-graph-szbj
---

Create DB schema: persons, platform_identities, entities (with content_embedding vector(768), last_accessed), edges. Add ivfflat index for vectors (vector(768) — sentence-transformers dimension), GIN for full-text, index on last_accessed. Include docker-compose for local Postgres + pgvector.
