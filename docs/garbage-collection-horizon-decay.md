---
date: 2026-03-18
title: "Garbage Collection for the Knowledge Graph"
tags: [clawgraph, garbage-collection, knowledge-graph]
---

# Garbage Collection

Entities are removed from the knowledge graph when they haven't been accessed within the retention window. While in the graph, everything is stored at full fidelity. No summarisation, no compression, no scoring model. Just a timestamp and a threshold.

## How It Works

Every entity has a `last_accessed` timestamp, updated when:
- **The user visits the source** — browser extension emits an observation event, server updates `last_accessed` for the corresponding entities
- **The agent uses the entity** — when the agent reads or traverses an entity during a query, it updates `last_accessed`

GC runs periodically (daily). Any entity where `now() - last_accessed > retention_period` is removed.

## Schema

```sql
CREATE TABLE entities (
  id            UUID PRIMARY KEY,
  type          TEXT NOT NULL,        -- Person, Message, Document, Channel, Task
  source        TEXT NOT NULL,        -- slack, jira, gdocs, etc.
  source_id     TEXT NOT NULL,        -- channel ID, ticket key, doc ID
  content       JSONB NOT NULL,       -- full content, source-specific structure
  importance    FLOAT DEFAULT 0.5,    -- optional, for future use
  created_at    TIMESTAMPTZ DEFAULT now(),
  last_accessed TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_entities_last_accessed ON entities(last_accessed);
```

## GC Query

```sql
DELETE FROM entities
WHERE last_accessed < now() - INTERVAL '90 days';
```

Edges referencing deleted entities are removed via `ON DELETE CASCADE`.

## Retention Period

Default: **90 days** since last access.

Configurable per deployment. Shorter for high-volume environments where the graph grows quickly. Longer for roles where old context stays relevant (e.g., a manager revisiting quarterly planning docs).

## Access Signals

| Source | When `last_accessed` is updated |
|--------|-------------------------------|
| Browser extension | User visits a URL → server fetches/refreshes entities → updates timestamp |
| Agent traversal | Agent reads an entity or follows an edge during a query → updates timestamp |
| Agent-initiated fetch | Agent proactively fetches a linked entity (e.g., following a ticket reference) → updates timestamp |

The agent keeping things alive is the important bit. If the user asks "what's the status of the billing migration?" and the agent traverses a chain of Slack messages → Jira ticket → design doc to answer, all of those entities get their timestamps refreshed. Context that's actively useful stays in the graph even if the user hasn't visited it in the browser recently.

## Cascade Rules

- Deleting an entity removes all its edges (`ON DELETE CASCADE`)
- `Person` entities are only removed when they have zero remaining edges
- Removing a `Channel` entity removes its messages (they'd already be expired individually, but cascade catches stragglers)

## Open Questions

1. **Retention period tuning.** 90 days is a guess. Could track graph size over time and adjust, or let users configure it.
2. **Per-source retention?** Slack messages might warrant a shorter window than Confluence pages. Simpler to start uniform and adjust if needed.
3. **Soft vs. hard delete?** Hard delete is simpler. If the user revisits, the API connector re-fetches fresh content anyway.
