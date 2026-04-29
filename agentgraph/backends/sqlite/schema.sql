-- AgentGraph SQLite schema
-- Requires: SQLite 3.35+ (RETURNING clause) — Python 3.12 ships with 3.40+

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS entities (
    id                 TEXT PRIMARY KEY,
    entity_type        TEXT NOT NULL,
    platform           TEXT NOT NULL,
    platform_entity_id TEXT NOT NULL,
    title              TEXT,
    content            TEXT,
    content_embedding  BLOB,  -- raw float32 bytes: struct.pack('{n}f', *vec)
    metadata           TEXT NOT NULL DEFAULT '{}',
    created_at         TEXT,  -- ISO8601 UTC
    updated_at         TEXT,  -- ISO8601 UTC
    synced_at          TEXT,  -- ISO8601 UTC
    last_accessed      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (platform, platform_entity_id)
);

CREATE TABLE IF NOT EXISTS edges (
    id               TEXT PRIMARY KEY,
    edge_type        TEXT NOT NULL,
    source_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    platform         TEXT,
    properties       TEXT NOT NULL DEFAULT '{}',
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (edge_type, source_entity_id, target_entity_id)
);

CREATE TABLE IF NOT EXISTS observations (
    id         TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    url        TEXT NOT NULL,
    title      TEXT,
    tab_id     INTEGER,
    timestamp  TEXT NOT NULL,  -- ISO8601 UTC
    evaluated  INTEGER NOT NULL DEFAULT 0,
    meta       TEXT,           -- JSON string
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    source     TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Entity indexes
CREATE INDEX IF NOT EXISTS idx_entities_type         ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_platform     ON entities(platform);
CREATE INDEX IF NOT EXISTS idx_entities_platform_eid ON entities(platform, platform_entity_id);
CREATE INDEX IF NOT EXISTS idx_entities_last_accessed ON entities(last_accessed);

-- Edge indexes
CREATE INDEX IF NOT EXISTS idx_edges_source  ON edges(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_target  ON edges(target_entity_id);

-- Observation indexes
CREATE INDEX IF NOT EXISTS idx_observations_timestamp ON observations(timestamp);
CREATE INDEX IF NOT EXISTS idx_observations_pending   ON observations(evaluated, tab_id) WHERE evaluated = 0;

-- FTS5 for full-text search (tokenize=porter ascii for stemming)
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    id      UNINDEXED,
    title,
    content,
    tokenize='porter ascii'
);
