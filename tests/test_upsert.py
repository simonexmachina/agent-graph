"""Tests for the entity/edge upsert layer and GC."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest

from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.connectors.base import (
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
)
from agentgraph.core.context import set_backend
from agentgraph.graph.upsert import upsert_batch


@pytest.fixture()
async def sqlite_backend() -> AsyncGenerator[SQLiteBackend, None]:
    backend = SQLiteBackend(":memory:")
    await backend.initialize()
    set_backend(backend)
    yield backend
    await backend.close()


# ---------------------------------------------------------------------------
# FetchPolicy unit tests (no DB needed)
# ---------------------------------------------------------------------------

def test_fetch_policy_first_visit() -> None:
    policy = FetchPolicy(stale_after_seconds=300)
    assert policy.decide(None) == FetchPolicy.FIRST_VISIT


def test_fetch_policy_fresh() -> None:
    policy = FetchPolicy(stale_after_seconds=300)
    recent = datetime.now(UTC) - timedelta(seconds=60)
    assert policy.decide(recent) == FetchPolicy.FRESH


def test_fetch_policy_stale() -> None:
    policy = FetchPolicy(stale_after_seconds=300)
    old = datetime.now(UTC) - timedelta(seconds=400)
    assert policy.decide(old) == FetchPolicy.INCREMENTAL


async def test_upsert_person_with_email(sqlite_backend: SQLiteBackend) -> None:
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

    row = await sqlite_backend._fetchone(
        """
        SELECT * FROM entities
        WHERE entity_type = 'Person' AND platform_entity_id = ?
        """,
        ["alice@example.com"],
    )
    assert row is not None
    assert row["title"] == "Alice"
    assert row["platform"] == "canonical"


async def test_upsert_person_idempotent(sqlite_backend: SQLiteBackend) -> None:
    person = PersonRecord(
        platform="slack",
        platform_user_id="U999",
        canonical_email="bob@example.com",
        display_name="Bob",
    )
    await upsert_batch(EntityBatch(persons=[person]))
    await upsert_batch(EntityBatch(persons=[person]))

    count = await sqlite_backend._fetchval(
        """
        SELECT count(*) FROM entities
        WHERE entity_type = 'Person' AND platform_entity_id = ?
        """,
        ["bob@example.com"],
    )
    assert count == 1


async def test_upsert_entity_and_edge(sqlite_backend: SQLiteBackend) -> None:
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

    entity = await sqlite_backend._fetchone(
        "SELECT * FROM entities WHERE platform_entity_id = ?",
        ["doc-abc"],
    )
    assert entity is not None
    assert entity["title"] == "Project Plan"
    assert entity["content_embedding"] is not None

    edge_count = await sqlite_backend._fetchval("SELECT count(*) FROM edges")
    assert edge_count == 1


async def test_upsert_edge_to_existing_person_sqlite(sqlite_backend: SQLiteBackend) -> None:
    await upsert_batch(
        EntityBatch(
            persons=[
                PersonRecord(
                    platform="slack",
                    platform_user_id="T1/U1",
                    display_name="Alice",
                )
            ]
        )
    )

    await upsert_batch(
        EntityBatch(
            entities=[
                EntityRecord(
                    entity_type="Message",
                    platform="slack",
                    platform_entity_id="T1/C1:123.456",
                    content="hello <@U1>",
                )
            ],
            edges=[
                EdgeRecord(
                    edge_type="mentions",
                    source_platform_entity_id="T1/C1:123.456",
                    target_platform_user_id="T1/U1",
                    platform="slack",
                )
            ],
        )
    )

    edge_count = await sqlite_backend._fetchval("SELECT count(*) FROM edges")
    assert edge_count == 1


async def test_unify_persons_merges_edges_and_identity_metadata_sqlite(
    sqlite_backend: SQLiteBackend,
) -> None:
    from agentgraph.graph.person import unify_persons

    await upsert_batch(
        EntityBatch(
            persons=[
                PersonRecord(
                    platform="gmail",
                    platform_user_id="simon.wade@gmail.com",
                    canonical_email="simon.wade@gmail.com",
                    display_name="Simon Wade",
                ),
                PersonRecord(
                    platform="slack",
                    platform_user_id="T1/U1",
                    platform_username="simon.wade",
                    display_name="Simon",
                ),
                PersonRecord(
                    platform="discord",
                    platform_user_id="D1",
                    platform_username="simon",
                    display_name="simon",
                ),
            ],
            entities=[
                EntityRecord(
                    entity_type="Message",
                    platform="gmail",
                    platform_entity_id="gmail-msg-1",
                    content="email hello",
                ),
                EntityRecord(
                    entity_type="Message",
                    platform="slack",
                    platform_entity_id="slack-msg-1",
                    content="slack hello",
                ),
                EntityRecord(
                    entity_type="Message",
                    platform="discord",
                    platform_entity_id="discord-msg-1",
                    content="discord hello",
                ),
            ],
            edges=[
                EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id="simon.wade@gmail.com",
                    target_platform_entity_id="gmail-msg-1",
                    platform="gmail",
                ),
                EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id="T1/U1",
                    target_platform_entity_id="slack-msg-1",
                    platform="slack",
                ),
                EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id="D1",
                    target_platform_entity_id="discord-msg-1",
                    platform="discord",
                ),
            ],
        )
    )

    primary_id = await sqlite_backend._fetchval(
        "SELECT id FROM entities WHERE platform_entity_id = ?",
        ["simon.wade@gmail.com"],
    )
    slack_id = await sqlite_backend._fetchval(
        "SELECT id FROM entities WHERE platform_entity_id = ?",
        ["slack:T1/U1"],
    )
    discord_id = await sqlite_backend._fetchval(
        "SELECT id FROM entities WHERE platform_entity_id = ?",
        ["discord:D1"],
    )

    result = await unify_persons(primary_id, [slack_id, discord_id])

    assert result["merged_count"] == 2
    assert await sqlite_backend.get_entity_by_id(slack_id) is None
    assert await sqlite_backend.get_entity_by_id(discord_id) is None
    primary = await sqlite_backend.get_entity_by_id(primary_id)
    assert primary is not None
    assert primary["metadata"]["slack_user_id"] == "T1/U1"
    assert primary["metadata"]["discord_user_id"] == "D1"

    source_count = await sqlite_backend._fetchval(
        """
        SELECT count(DISTINCT source_entity_id)
        FROM edges
        WHERE edge_type = 'authored'
        """
    )
    assert source_count == 1

    slack_authored = await sqlite_backend.query_by_filter(
        "Message",
        filters={},
        limit=10,
        order_by="last_accessed",
        since=None,
        authored_by=["T1/U1"],
    )
    assert {entity["platform_entity_id"] for entity in slack_authored} == {
        "discord-msg-1",
        "gmail-msg-1",
        "slack-msg-1",
    }

    await upsert_batch(
        EntityBatch(
            persons=[
                PersonRecord(
                    platform="slack",
                    platform_user_id="T1/U1",
                    platform_username="simon.wade",
                    display_name="Simon",
                )
            ]
        )
    )
    person_count = await sqlite_backend._fetchval(
        """
        SELECT count(*)
        FROM entities
        WHERE entity_type = 'Person'
        """
    )
    assert person_count == 1
    refreshed_primary = await sqlite_backend.get_entity_by_id(primary_id)
    assert refreshed_primary is not None
    assert refreshed_primary["metadata"]["slack_user_id"] == "T1/U1"
