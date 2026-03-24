-- AgentGraph knowledge graph schema
-- Requires: PostgreSQL 16+ with pgvector extension

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- for future trigram-based fuzzy search

-- ---------------------------------------------------------------------------
-- Persons: canonical identity keyed by email
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS persons (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_email TEXT UNIQUE,          -- NULL for email-less identities
    display_name TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_accessed TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_persons_email ON persons (canonical_email)
    WHERE canonical_email IS NOT NULL;

-- ---------------------------------------------------------------------------
-- Platform identities: links a Person to a platform-specific ID
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_identities (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id        UUID NOT NULL REFERENCES persons (id) ON DELETE CASCADE,
    platform         TEXT NOT NULL,        -- 'slack' | 'gdocs' | etc.
    platform_user_id TEXT NOT NULL,
    platform_username TEXT,
    raw_profile      JSONB NOT NULL DEFAULT '{}',
    UNIQUE (platform, platform_user_id)
);

CREATE INDEX IF NOT EXISTS idx_platform_identities_person ON platform_identities (person_id);

-- ---------------------------------------------------------------------------
-- Entities: messages, documents, tasks, channels, etc.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type      TEXT NOT NULL,        -- 'Message' | 'Document' | 'Channel' | 'Task' | 'Project'
    platform         TEXT NOT NULL,        -- 'slack' | 'gdocs'
    platform_entity_id TEXT NOT NULL,
    title            TEXT,
    content          TEXT,
    content_embedding vector(384),         -- sentence-transformers all-MiniLM-L6-v2
    metadata         JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ,
    updated_at       TIMESTAMPTZ,
    synced_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
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

CREATE INDEX IF NOT EXISTS idx_entities_type     ON entities (entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_platform ON entities (platform);
CREATE INDEX IF NOT EXISTS idx_entities_last_accessed ON entities (last_accessed);

-- ---------------------------------------------------------------------------
-- Edges: typed relationships between entities and/or persons
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS edges (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    edge_type        TEXT NOT NULL,        -- 'authored' | 'posted_in' | 'replied_to' | 'mentions' | 'references'
    source_entity_id UUID REFERENCES entities (id) ON DELETE CASCADE,
    source_person_id UUID REFERENCES persons (id)  ON DELETE CASCADE,
    target_entity_id UUID REFERENCES entities (id) ON DELETE CASCADE,
    target_person_id UUID REFERENCES persons (id)  ON DELETE CASCADE,
    platform         TEXT,
    properties       JSONB NOT NULL DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT edges_has_source CHECK (
        source_entity_id IS NOT NULL OR source_person_id IS NOT NULL
    ),
    CONSTRAINT edges_has_target CHECK (
        target_entity_id IS NOT NULL OR target_person_id IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_edges_source_entity ON edges (source_entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_target_entity ON edges (target_entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_source_person ON edges (source_person_id);
CREATE INDEX IF NOT EXISTS idx_edges_target_person ON edges (target_person_id);
CREATE INDEX IF NOT EXISTS idx_edges_type           ON edges (edge_type);

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
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_observations_timestamp  ON observations (timestamp);
CREATE INDEX IF NOT EXISTS idx_observations_evaluated  ON observations (evaluated) WHERE NOT evaluated;
