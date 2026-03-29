-- AgentGraph knowledge graph schema
-- Requires: PostgreSQL 16+ with pgvector extension

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for future trigram-based fuzzy search

-- ---------------------------------------------------------------------------
-- Entities: messages, documents, channels, persons, etc.
-- entity_type: 'Message' | 'Document' | 'Channel' | 'Task' | 'Person'
-- platform:    'slack' | 'gdocs' | 'canonical' (Person nodes use 'canonical')
-- For Person nodes: platform='canonical', platform_entity_id=canonical_email
--   (or 'platform:user_id' if email unknown), metadata includes platform user IDs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type      TEXT NOT NULL,
    platform         TEXT NOT NULL,
    platform_entity_id TEXT NOT NULL,
    title            TEXT,
    content          TEXT,
    content_embedding vector(384),         -- sentence-transformers all-MiniLM-L6-v2
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ,
    synced_at        TIMESTAMPTZ,
    last_accessed    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (platform, platform_entity_id)
);

-- Vector similarity search (IVFFlat; HNSW requires pgvector 0.5+)
CREATE INDEX IF NOT EXISTS idx_entities_embedding ON entities
    USING ivfflat (content_embedding vector_cosine_ops)
    WITH (lists = 100)
    WHERE content_embedding IS NOT NULL;

-- Full-text search
CREATE INDEX IF NOT EXISTS idx_entities_fulltext ON entities
    USING gin (
        to_tsvector('english',
            coalesce(title, '') || ' ' || coalesce(content, ''))
    );

CREATE INDEX IF NOT EXISTS idx_entities_type         ON entities (entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_platform     ON entities (platform);
CREATE INDEX IF NOT EXISTS idx_entities_last_accessed ON entities (last_accessed);

-- ---------------------------------------------------------------------------
-- Edges: typed relationships between entities (including Person entities)
-- edge_type: 'authored' | 'posted_in' | 'replied_to' | 'mentions' |
--            'collaborated' | 'references'
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS edges (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edge_type        TEXT NOT NULL,
    source_entity_id UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    platform         TEXT,
    properties       JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_edges_source_entity ON edges (source_entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_target_entity ON edges (target_entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_type          ON edges (edge_type);

CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique ON edges (
    edge_type, source_entity_id, target_entity_id
);

-- ---------------------------------------------------------------------------
-- Observations: raw focus/blur events from the browser extension
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS observations (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,    -- 'focus' | 'blur'
    url        TEXT NOT NULL,
    title      TEXT,
    tab_id     INTEGER,
    timestamp  TIMESTAMPTZ NOT NULL,
    evaluated  BOOLEAN NOT NULL DEFAULT false,  -- has dwell evaluator processed this?
    meta       JSONB,                           -- optional platform metadata (e.g. gmail_message_id)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE observations ADD COLUMN IF NOT EXISTS meta JSONB;

CREATE INDEX IF NOT EXISTS idx_observations_timestamp  ON observations (timestamp);
CREATE INDEX IF NOT EXISTS idx_observations_evaluated  ON observations (evaluated) WHERE NOT evaluated;
