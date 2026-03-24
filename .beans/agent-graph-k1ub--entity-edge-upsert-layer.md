---
# agent-graph-k1ub
title: Entity + edge upsert layer
status: todo
type: task
priority: normal
created_at: 2026-03-24T10:20:17Z
updated_at: 2026-03-24T10:29:45Z
parent: agent-graph-af03
blocked_by:
    - agent-graph-hpnd
---

graph/upsert.py: idempotent upsert for entities (ON CONFLICT (platform, platform_entity_id) DO UPDATE), persons (ON CONFLICT (canonical_email)), edges. Auto-generate embeddings using sentence-transformers (all-MiniLM-L6-v2 or nomic-embed-text, 768 dimensions) for content field before insert. Model loaded once at startup. Update last_accessed on upsert.
