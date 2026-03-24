---
# agent-graph-i0jd
title: MCP server scaffold + search_entities tool
status: todo
type: task
created_at: 2026-03-24T10:20:28Z
updated_at: 2026-03-24T10:20:28Z
parent: agent-graph-414r
blocked_by:
    - agent-graph-k1ub
---

Set up mcp/ using the MCP Python SDK. Implement search_entities(query, entity_types?, limit=10): hybrid retrieval combining pgvector cosine similarity + tsvector full-text, merged via RRF scoring. Update last_accessed on all returned entities.
