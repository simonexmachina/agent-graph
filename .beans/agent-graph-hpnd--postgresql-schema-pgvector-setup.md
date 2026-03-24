---
# agent-graph-hpnd
title: PostgreSQL schema + pgvector setup
status: completed
type: task
priority: normal
created_at: 2026-03-24T10:18:53Z
updated_at: 2026-03-24T10:57:26Z
parent: agent-graph-szbj
---

Create DB schema: persons, platform_identities, entities (with content_embedding vector(768), last_accessed), edges. Add ivfflat index for vectors (vector(768) — sentence-transformers dimension), GIN for full-text, index on last_accessed. Include docker-compose for local Postgres + pgvector.

## Summary of Changes

- docker-compose.yml: pgvector/pgvector:pg17, healthcheck, named volume
- agentgraph/db/schema.sql: persons, platform_identities, entities (vector(384)), edges, observations
  - IVFFlat index on content_embedding, GIN on full-text, index on last_accessed
  - ON DELETE CASCADE on edges
  - All DDL idempotent (IF NOT EXISTS)
- agentgraph/db/connection.py: asyncpg pool management, apply_schema(), acquire() context manager
- 3 integration tests: table existence, pgvector extension, insert + cascade verify (all green)
