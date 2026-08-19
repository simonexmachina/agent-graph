from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.connectors.base import EntityBatch, EntityRecord
from agentgraph.demo import (
    DEMO_CREATED_AT,
    DEMO_FIXTURE_METADATA_KEY,
    DEMO_FIXTURE_METADATA_VALUE,
    RETRY_GUIDE_URL,
    WEBHOOK_ARTICLE_URL,
    add_demo,
    build_demo_batch,
    remove_demo,
)


def test_demo_batch_uses_real_graph_shapes() -> None:
    batch = build_demo_batch()

    assert len(batch.entities) == 9
    assert len(batch.persons) == 4
    assert len(batch.edges) == 15
    assert {entity.platform for entity in batch.entities} == {"slack", "gmail", "gdrive", "web"}
    assert {edge.edge_type for edge in batch.edges} == {
        "authored",
        "contains",
        "mentions",
        "participated_in",
        "posted_in",
        "references",
        "replied_to",
    }
    web_entities = [entity for entity in batch.entities if entity.platform == "web"]
    assert {entity.platform_entity_id for entity in web_entities} == {
        WEBHOOK_ARTICLE_URL,
        RETRY_GUIDE_URL,
    }
    assert all(not entity.is_stub for entity in web_entities)
    assert all(entity.content and len(entity.content) > 500 for entity in web_entities)


@pytest.mark.asyncio
async def test_demo_add_and_remove_marked_fixtures(tmp_path: Path) -> None:
    config_dir = tmp_path / "atlas-demo"

    result = await add_demo(config_dir)

    database_path = config_dir / "agentgraph.db"
    assert result["database"] == str(database_path)
    assert result["entities"] == 9
    assert result["persons"] == 3
    assert result["edges"] == 15
    with sqlite3.connect(database_path) as conn:
        conn.row_factory = sqlite3.Row
        alex = conn.execute(
            "SELECT metadata FROM entities WHERE entity_type = 'Person' AND platform_entity_id = ?",
            ["alex@agentgraph.demo"],
        ).fetchone()
        assert alex is not None
        alex_metadata = json.loads(alex["metadata"])
        assert alex_metadata["slack_user_id"] == "U_ALEX"
        assert alex_metadata["gdrive_user_id"] == "alex@agentgraph.demo"
        web_rows = conn.execute(
            """
            SELECT platform_entity_id, content, synced_at, observed_at
            FROM entities
            WHERE platform = 'web'
            """
        ).fetchall()
        assert {row["platform_entity_id"] for row in web_rows} == {
            WEBHOOK_ARTICLE_URL,
            RETRY_GUIDE_URL,
        }
        assert all(row["content"] and len(row["content"]) > 500 for row in web_rows)
        assert all(row["synced_at"] == DEMO_CREATED_AT for row in web_rows)
        assert all(row["observed_at"] is None for row in web_rows)
        marked = conn.execute(
            "SELECT count(*) FROM entities WHERE json_extract(metadata, ?) = ?",
            [f"$.{DEMO_FIXTURE_METADATA_KEY}", DEMO_FIXTURE_METADATA_VALUE],
        ).fetchone()[0]
        assert marked == 12
        search_hits = conn.execute(
            "SELECT title FROM entities_fts WHERE entities_fts MATCH 'webhook'"
        ).fetchall()
        assert search_hits

    result = await remove_demo(config_dir)
    assert result == {"database": str(database_path), "removed": 12}
    with sqlite3.connect(database_path) as conn:
        assert conn.execute("SELECT count(*) FROM entities").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM edges").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_demo_add_preserves_existing_environment(tmp_path: Path) -> None:
    config_dir = tmp_path / "existing-config"
    config_dir.mkdir()
    environment_path = config_dir / ".env"
    environment = "AGENTGRAPH_CONFIG_DIR=/tmp/agentgraph-atlas-demo\n"
    environment_path.write_text(environment, encoding="utf-8")

    result = await add_demo(config_dir)

    assert result["database"] == str(config_dir / "agentgraph.db")
    assert environment_path.read_text(encoding="utf-8") == environment


@pytest.mark.asyncio
async def test_demo_remove_preserves_unmarked_entities(tmp_path: Path) -> None:
    config_dir = tmp_path / "mixed-graph"
    database_path = config_dir / "agentgraph.db"
    backend = SQLiteBackend(str(database_path), vector_mode="bm25-only")
    await backend.initialize()
    try:
        await backend.upsert_batch(
            EntityBatch(
                entities=[
                    EntityRecord(
                        entity_type="Document",
                        platform="local",
                        platform_entity_id="keep-me",
                        title="Unrelated document",
                    )
                ]
            ),
            person_embeddings={},
            entity_embeddings={},
        )
    finally:
        await backend.close()

    await add_demo(config_dir)
    result = await remove_demo(config_dir)

    assert result["removed"] == 12
    with sqlite3.connect(database_path) as conn:
        row = conn.execute(
            "SELECT title FROM entities WHERE platform = ? AND platform_entity_id = ?",
            ["local", "keep-me"],
        ).fetchone()
        assert row == ("Unrelated document",)
