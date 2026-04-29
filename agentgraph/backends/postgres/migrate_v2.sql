-- Migration: move persons / platform_identities into the entities table.
-- Safe to run multiple times (all operations are guarded by IF EXISTS checks).

DO $$
BEGIN
  -- Only run if the old persons table still exists
  IF NOT EXISTS (
      SELECT 1 FROM information_schema.tables
      WHERE table_schema = 'public' AND table_name = 'persons'
  ) THEN
    RETURN;
  END IF;

  -- 1. Insert persons into entities
  INSERT INTO entities (
      entity_type, platform, platform_entity_id, title, content,
      metadata, created_at, synced_at, last_accessed
  )
  SELECT
      'Person',
      'canonical',
      COALESCE(p.canonical_email, p.id::text),
      p.display_name,
      p.canonical_email,   -- email as content for full-text search
      jsonb_strip_nulls(
          jsonb_build_object(
              'canonical_email', p.canonical_email,
              'display_name',    p.display_name
          ) ||
          COALESCE(
              (SELECT jsonb_object_agg(pi.platform || '_user_id', pi.platform_user_id)
               FROM platform_identities pi
               WHERE pi.person_id = p.id),
              '{}'::jsonb
          )
      ),
      p.created_at,
      now(),
      p.last_accessed
  FROM persons p
  ON CONFLICT (platform, platform_entity_id) DO UPDATE SET
      title         = COALESCE(EXCLUDED.title, entities.title),
      metadata      = entities.metadata || EXCLUDED.metadata,
      last_accessed = GREATEST(entities.last_accessed, EXCLUDED.last_accessed);

  -- 2. Migrate source_person_id → source_entity_id on edges
  UPDATE edges e
  SET source_entity_id = ent.id
  FROM persons p
  JOIN entities ent
    ON ent.platform = 'canonical'
   AND ent.platform_entity_id = COALESCE(p.canonical_email, p.id::text)
  WHERE e.source_person_id = p.id
    AND e.source_entity_id IS NULL;

  -- 3. Migrate target_person_id → target_entity_id on edges
  UPDATE edges e
  SET target_entity_id = ent.id
  FROM persons p
  JOIN entities ent
    ON ent.platform = 'canonical'
   AND ent.platform_entity_id = COALESCE(p.canonical_email, p.id::text)
  WHERE e.target_person_id = p.id
    AND e.target_entity_id IS NULL;

  -- 4. Remove edges that couldn't be fully resolved
  DELETE FROM edges
  WHERE source_entity_id IS NULL OR target_entity_id IS NULL;

  -- 5. Drop the old unique index (included person columns)
  DROP INDEX IF EXISTS idx_edges_unique;

  -- 6. Drop person FK columns from edges
  ALTER TABLE edges
      DROP CONSTRAINT IF EXISTS edges_has_source,
      DROP CONSTRAINT IF EXISTS edges_has_target,
      DROP COLUMN IF EXISTS source_person_id,
      DROP COLUMN IF EXISTS target_person_id;

  -- 7. Add NOT NULL constraints
  ALTER TABLE edges
      ALTER COLUMN source_entity_id SET NOT NULL,
      ALTER COLUMN target_entity_id SET NOT NULL;

  -- 8. Re-create clean unique index
  CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_unique ON edges (
      edge_type, source_entity_id, target_entity_id
  );

  -- 9. Clean up old person indexes
  DROP INDEX IF EXISTS idx_edges_source_person;
  DROP INDEX IF EXISTS idx_edges_target_person;
  DROP INDEX IF EXISTS idx_persons_email;
  DROP INDEX IF EXISTS idx_platform_identities_person;

  -- 10. Drop old tables
  DROP TABLE IF EXISTS platform_identities;
  DROP TABLE IF EXISTS persons;

END $$;

-- Make synced_at nullable so stub entities (never fetched) are correctly identified
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'entities' AND column_name = 'synced_at'
      AND is_nullable = 'NO'
  ) THEN
    ALTER TABLE entities ALTER COLUMN synced_at DROP NOT NULL;
    ALTER TABLE entities ALTER COLUMN synced_at DROP DEFAULT;
  END IF;
END $$;
