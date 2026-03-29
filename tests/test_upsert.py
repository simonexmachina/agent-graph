"""Tests for the entity/edge upsert layer and GC."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agentgraph.connectors.base import (
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
)
from agentgraph.db.connection import apply_schema, close_pool, get_pool
from agentgraph.graph.upsert import upsert_batch


# ---------------------------------------------------------------------------
# FetchPolicy unit tests (no DB needed)
# ---------------------------------------------------------------------------

def test_fetch_policy_first_visit() -> None:
    policy = FetchPolicy(stale_after_seconds=300)
    assert policy.decide(None) == FetchPolicy.FIRST_VISIT


def test_fetch_policy_fresh() -> None:
    policy = FetchPolicy(stale_after_seconds=300)
    recent = datetime.now(timezone.utc) - timedelta(seconds=60)
    assert policy.decide(recent) == FetchPolicy.FRESH


def test_fetch_policy_stale() -> None:
    policy = FetchPolicy(stale_after_seconds=300)
    old = datetime.now(timezone.utc) - timedelta(seconds=400)
    assert policy.decide(old) == FetchPolicy.INCREMENTAL


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def db():
    await apply_schema()
    yield
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM edges")
        await conn.execute("DELETE FROM entities")
    await close_pool()


@pytest.mark.integration
async def test_upsert_person_with_email() -> None:
    batch = EntityBatch(
        persons=[
            PersonRecord(
                platform="slack",
                platform_user_id="U123",
                canonical_email="alice@example.com",
                display_name="Alice",
            )
        ]
    )
    await upsert_batch(batch)

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM entities
            WHERE entity_type = 'Person' AND platform_entity_id = 'alice@example.com'
            """
        )
    assert row is not None
    assert row["title"] == "Alice"
    assert row["platform"] == "canonical"


@pytest.mark.integration
async def test_upsert_person_idempotent() -> None:
    person = PersonRecord(
        platform="slack",
        platform_user_id="U999",
        canonical_email="bob@example.com",
        display_name="Bob",
    )
    await upsert_batch(EntityBatch(persons=[person]))
    await upsert_batch(EntityBatch(persons=[person]))

    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            """
            SELECT count(*) FROM entities
            WHERE entity_type = 'Person' AND platform_entity_id = 'bob@example.com'
            """
        )
    assert count == 1


@pytest.mark.integration
async def test_upsert_entity_and_edge() -> None:
    batch = EntityBatch(
        persons=[
            PersonRecord(
                platform="gdocs",
                platform_user_id="user-1",
                canonical_email="carol@example.com",
                display_name="Carol",
            )
        ],
        entities=[
            EntityRecord(
                entity_type="Document",
                platform="gdocs",
                platform_entity_id="doc-abc",
                title="Project Plan",
                content="We will build an amazing product.",
            )
        ],
        edges=[
            EdgeRecord(
                edge_type="authored",
                source_platform_user_id="user-1",
                target_platform_entity_id="doc-abc",
                platform="gdocs",
            )
        ],
    )
    await upsert_batch(batch)

    pool = await get_pool()
    async with pool.acquire() as conn:
        entity = await conn.fetchrow(
            "SELECT * FROM entities WHERE platform_entity_id = 'doc-abc'"
        )
        assert entity is not None
        assert entity["title"] == "Project Plan"
        assert entity["content_embedding"] is not None

        edge_count = await conn.fetchval("SELECT count(*) FROM edges")
        assert edge_count == 1


@pytest.mark.integration
async def test_gc_removes_stale_entities() -> None:
    from agentgraph.graph.gc import run_gc

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entities (entity_type, platform, platform_entity_id, last_accessed)
            VALUES ('Message', 'slack', 'old-msg-1', now() - INTERVAL '100 days')
            """
        )
        await conn.execute(
            """
            INSERT INTO entities (entity_type, platform, platform_entity_id, last_accessed)
            VALUES ('Message', 'slack', 'new-msg-1', now() - INTERVAL '1 day')
            """
        )

    deleted = await run_gc()
    assert deleted >= 1

    async with pool.acquire() as conn:
        old = await conn.fetchval(
            "SELECT count(*) FROM entities WHERE platform_entity_id = 'old-msg-1'"
        )
        new = await conn.fetchval(
            "SELECT count(*) FROM entities WHERE platform_entity_id = 'new-msg-1'"
        )
    assert old == 0
    assert new == 1
