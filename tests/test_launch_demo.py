from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.seed_launch_demo import (
    DEMO_CREATED_AT,
    RETRY_GUIDE_URL,
    WEBHOOK_ARTICLE_URL,
    build_demo_batch,
    seed_demo,
    validate_demo_config_dir,
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


def test_demo_refuses_default_config_directory() -> None:
    with pytest.raises(ValueError, match="default"):
        validate_demo_config_dir(Path.home() / ".agentgraph")


@pytest.mark.asyncio
async def test_seed_demo_creates_isolated_searchable_graph(tmp_path: Path) -> None:
    config_dir = tmp_path / "atlas-demo"

    result = await seed_demo(config_dir)

    database_path = config_dir / "agentgraph.db"
    assert result["database"] == str(database_path)
    assert result["entities"] == 12
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
        search_hits = conn.execute(
            "SELECT title FROM entities_fts WHERE entities_fts MATCH 'webhook'"
        ).fetchall()
        assert search_hits

    with pytest.raises(FileExistsError):
        await seed_demo(config_dir)
