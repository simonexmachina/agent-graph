"""Tests for the entity/edge upsert layer and expiration."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agentgraph.backends.sqlite.backend import SQLiteBackend
from agentgraph.connectors.base import (
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
    SourceReference,
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


async def test_changed_person_upsert_returns_committed_snapshot(
    sqlite_backend: SQLiteBackend,
) -> None:
    person = PersonRecord(
        platform="slack",
        platform_user_id="U123",
        canonical_email="alice@example.com",
        display_name="Alice",
    )
    inserted = await sqlite_backend.upsert_batch(EntityBatch(persons=[person]), {}, {})
    assert len(inserted) == 1
    assert inserted[0]["entity_type"] == "Person"

    updated_person = person.model_copy(update={"display_name": "Alice Updated"})
    updated = await sqlite_backend.upsert_batch(EntityBatch(persons=[updated_person]), {}, {})

    assert len(updated) == 1
    assert updated[0]["entity_type"] == "Person"
    assert updated[0]["title"] == "Alice Updated"


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


async def test_list_recent_metadata_by_edge_target_returns_newest_metadata_per_target(
    sqlite_backend: SQLiteBackend,
) -> None:
    await upsert_batch(
        EntityBatch(
            entities=[
                EntityRecord(
                    entity_type="Folder",
                    platform="rss",
                    platform_entity_id="feed/a",
                ),
                EntityRecord(
                    entity_type="Folder",
                    platform="rss",
                    platform_entity_id="feed/b",
                ),
                EntityRecord(
                    entity_type="Document",
                    platform="rss",
                    platform_entity_id="feed-a-old",
                    title="A old",
                    content="old content",
                    metadata={"web_url": "https://a/old"},
                    source_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
                EntityRecord(
                    entity_type="Document",
                    platform="rss",
                    platform_entity_id="feed-a-new",
                    title="A new",
                    content="new content",
                    metadata={"web_url": "https://a/new"},
                    source_updated_at=datetime(2026, 1, 2, tzinfo=UTC),
                ),
                EntityRecord(
                    entity_type="Document",
                    platform="rss",
                    platform_entity_id="feed-b",
                    title="B",
                    content="other content",
                    metadata={"web_url": "https://b/post"},
                    source_updated_at=datetime(2026, 1, 3, tzinfo=UTC),
                ),
                EntityRecord(
                    entity_type="Document",
                    platform="rss",
                    platform_entity_id="wrong-edge",
                    metadata={"web_url": "https://a/wrong"},
                ),
            ],
            edges=[
                EdgeRecord(
                    edge_type="posted_in",
                    source_platform_entity_id="feed-a-old",
                    target_platform_entity_id="feed/a",
                    platform="rss",
                ),
                EdgeRecord(
                    edge_type="posted_in",
                    source_platform_entity_id="feed-a-new",
                    target_platform_entity_id="feed/a",
                    platform="rss",
                ),
                EdgeRecord(
                    edge_type="posted_in",
                    source_platform_entity_id="feed-b",
                    target_platform_entity_id="feed/b",
                    platform="rss",
                ),
                EdgeRecord(
                    edge_type="references",
                    source_platform_entity_id="wrong-edge",
                    target_platform_entity_id="feed/a",
                    platform="rss",
                ),
            ],
        )
    )
    await sqlite_backend._execute(
        "UPDATE entities SET updated_at = ? WHERE platform_entity_id = ?",
        ["2026-01-01T00:00:00Z", "feed-a-old"],
    )
    await sqlite_backend._execute(
        "UPDATE entities SET updated_at = ? WHERE platform_entity_id = ?",
        ["2026-01-02T00:00:00Z", "feed-a-new"],
    )

    with patch.object(sqlite_backend, "_fetchall", wraps=sqlite_backend._fetchall) as fetchall:
        metadata_by_target = await sqlite_backend.list_recent_metadata_by_edge_target(
            "Document",
            {"platform": "rss"},
            "posted_in",
            "rss",
            ["feed/a", "feed/b"],
            1,
            "updated_at",
        )

    assert metadata_by_target == {
        "feed/a": [{"web_url": "https://a/new"}],
        "feed/b": [{"web_url": "https://b/post"}],
    }
    assert fetchall.await_args is not None
    sql, params = fetchall.await_args.args
    plan = await sqlite_backend._fetchall(f"EXPLAIN QUERY PLAN {sql}", params)
    details = [str(row["detail"]) for row in plan]
    assert any(
        "SEARCH target" in detail and "platform=? AND platform_entity_id=?" in detail
        for detail in details
    )
    assert any("idx_edges_target_type_source" in detail for detail in details)
    assert not any("SCAN source" in detail for detail in details)


async def test_list_recent_metadata_by_edge_target_returns_empty_for_no_work(
    sqlite_backend: SQLiteBackend,
) -> None:
    assert (
        await sqlite_backend.list_recent_metadata_by_edge_target(
            "Document", {}, "posted_in", "rss", [], 8, "updated_at"
        )
        == {}
    )
    assert (
        await sqlite_backend.list_recent_metadata_by_edge_target(
            "Document", {}, "posted_in", "rss", ["feed/a"], 0, "updated_at"
        )
        == {}
    )


async def test_upsert_batch_maintains_one_current_fts_row_per_entity(
    sqlite_backend: SQLiteBackend,
) -> None:
    entity = EntityRecord(
        entity_type="Document",
        platform="gdocs",
        platform_entity_id="doc-fts",
        title="Original title",
        content="original wording",
    )
    await sqlite_backend.upsert_batch(EntityBatch(entities=[entity]), {}, {})
    updated = entity.model_copy(update={"title": "Updated title", "content": "replacement wording"})
    await sqlite_backend.upsert_batch(EntityBatch(entities=[updated]), {}, {})

    rows = await sqlite_backend._fetchall(
        "SELECT id, title, content FROM entities_fts WHERE id = (SELECT id FROM entities WHERE platform_entity_id = ?)",
        ["doc-fts"],
    )
    assert len(rows) == 1
    assert rows[0]["title"] == "Updated title"
    assert rows[0]["content"] == "replacement wording"


async def test_upsert_preserves_source_updated_at_when_connector_omits_it(
    sqlite_backend: SQLiteBackend,
) -> None:
    original_updated_at = datetime(2026, 6, 8, 1, 23, 45, tzinfo=UTC)
    entity = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/unchanged",
        title="Original title",
        content="Original content",
        source_updated_at=original_updated_at,
    )
    await sqlite_backend.upsert_batch(EntityBatch(entities=[entity]), {}, {})

    unchanged = entity.model_copy(update={"source_updated_at": None})
    await sqlite_backend.upsert_batch(EntityBatch(entities=[unchanged]), {}, {})

    stored = await sqlite_backend.get_entity_by_platform(
        "web", "https://example.com/unchanged"
    )
    assert stored is not None
    assert stored["source_updated_at"] == "2026-06-08T01:23:45Z"


async def test_identical_upsert_preserves_observed_at(sqlite_backend: SQLiteBackend) -> None:
    entity = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/unchanged",
        title="Original title",
        content="Original content",
    )
    await sqlite_backend.upsert_batch(EntityBatch(entities=[entity]), {}, {})
    await sqlite_backend._execute(
        "UPDATE entities SET observed_at = ? WHERE platform = ? AND platform_entity_id = ?",
        ["2020-01-01T00:00:00Z", "web", "https://example.com/unchanged"],
    )

    await sqlite_backend.upsert_batch(EntityBatch(entities=[entity]), {}, {})

    stored = await sqlite_backend.get_entity_by_platform("web", "https://example.com/unchanged")
    assert stored is not None
    assert stored["observed_at"] == "2020-01-01T00:00:00Z"


async def test_owned_entity_resolves_parent_without_becoming_observed(
    sqlite_backend: SQLiteBackend,
) -> None:
    source_time = datetime(2026, 6, 8, 1, 23, 45, tzinfo=UTC)
    channel = EntityRecord(
        entity_type="Channel",
        platform="slack",
        platform_entity_id="T/C",
    )
    message = EntityRecord(
        entity_type="Message",
        platform="slack",
        platform_entity_id="T/C/1",
        content="hello",
        source_created_at=source_time,
        source_updated_at=source_time,
        retention_policy="owned",
        retention_parent_platform_entity_id="T/C",
    )

    await sqlite_backend.upsert_batch(EntityBatch(entities=[channel, message]), {}, {})

    stored_channel = await sqlite_backend.get_entity_by_platform("slack", "T/C")
    stored_message = await sqlite_backend.get_entity_by_platform("slack", "T/C/1")
    assert stored_channel is not None
    assert stored_message is not None
    assert stored_channel["observed_at"] is None
    assert stored_message["observed_at"] is None
    assert stored_message["retention_policy"] == "owned"
    assert stored_message["retention_parent_id"] == stored_channel["id"]
    assert stored_message["source_created_at"] == "2026-06-08T01:23:45Z"


async def test_changed_upsert_refreshes_updated_at_but_not_observed_at(
    sqlite_backend: SQLiteBackend,
) -> None:
    entity = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/changed",
        title="Original title",
        content="Original content",
    )
    inserted = await sqlite_backend.upsert_batch(EntityBatch(entities=[entity]), {}, {})
    assert len(inserted) == 1
    assert inserted[0]["platform_entity_id"] == "https://example.com/changed"
    await sqlite_backend._execute(
        "UPDATE entities SET observed_at = ?, updated_at = ? "
        "WHERE platform = ? AND platform_entity_id = ?",
        [
            "2020-01-01T00:00:00Z",
            "2020-01-01T00:00:00Z",
            "web",
            "https://example.com/changed",
        ],
    )

    changed = entity.model_copy(update={"content": "Changed content"})
    updated = await sqlite_backend.upsert_batch(EntityBatch(entities=[changed]), {}, {})

    stored = await sqlite_backend.get_entity_by_platform("web", "https://example.com/changed")
    assert stored is not None
    assert stored["observed_at"] == "2020-01-01T00:00:00Z"
    assert stored["updated_at"] > "2020-01-01T00:00:00Z"
    assert [snapshot["id"] for snapshot in updated] == [stored["id"]]
    assert updated[0]["content"] == "Changed content"


async def test_unchanged_upsert_returns_no_upserted_entity_snapshots(
    sqlite_backend: SQLiteBackend,
) -> None:
    entity = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/noop",
        content="Unchanged content",
    )

    inserted = await sqlite_backend.upsert_batch(EntityBatch(entities=[entity]), {}, {})
    assert len(inserted) == 1
    assert await sqlite_backend.upsert_batch(EntityBatch(entities=[entity]), {}, {}) == []


async def test_stub_insert_returns_one_upserted_snapshot(
    sqlite_backend: SQLiteBackend,
) -> None:
    stub = EntityRecord(
        entity_type="Document",
        platform="web",
        platform_entity_id="https://example.com/stub",
        is_stub=True,
    )

    inserted = await sqlite_backend.upsert_batch(EntityBatch(entities=[stub]), {}, {})
    assert len(inserted) == 1
    assert inserted[0]["platform_entity_id"] == "https://example.com/stub"
    assert inserted[0]["synced_at"] is None
    assert await sqlite_backend.upsert_batch(EntityBatch(entities=[stub]), {}, {}) == []


async def test_upsert_event_includes_reference_edge_created_after_storage_commit(
    sqlite_backend: SQLiteBackend,
) -> None:
    from agentgraph.connectors.feed import EntityUpsertMutation

    source_url = "https://example.com/source"
    target_url = "https://example.com/target"
    batch = EntityBatch(
        entities=[
            EntityRecord(
                entity_type="Document",
                platform="web",
                platform_entity_id=source_url,
                content=f"See {target_url}",
            )
        ]
    )
    target_ref = SourceReference(
        source="web",
        resource_type="document",
        resource_id=target_url,
    )

    with (
        patch("agentgraph.graph.upsert._build_embeddings", return_value=({}, {})),
        patch("agentgraph.server.router.classify_url", return_value=target_ref),
        patch("agentgraph.connectors.feed.notify_feed_connectors", new=AsyncMock()) as notify,
    ):
        await upsert_batch(batch)

    notify_args = notify.await_args
    assert notify_args is not None
    event = notify_args.args[0]
    assert isinstance(event, EntityUpsertMutation)
    assert event.entity.platform_entity_id == source_url
    assert len(event.edges) == 1
    assert event.edges[0].edge_type == "references"
    assert event.edges[0].source_ref == source_url
    assert event.edges[0].target_ref == target_url
    assert notify.await_count == 1


async def test_upsert_batch_skips_fts_rewrites_for_unchanged_text(
    sqlite_backend: SQLiteBackend,
) -> None:
    batch = EntityBatch(
        persons=[
            PersonRecord(
                platform="rss",
                platform_user_id="author-1",
                display_name="Author One",
            )
        ],
        entities=[
            EntityRecord(
                entity_type="Folder",
                platform="rss",
                platform_entity_id="feed/example",
                title="Example Feed",
                content="RSS feed: Example Feed",
            )
        ],
    )
    await sqlite_backend.upsert_batch(batch, {}, {})
    statements: list[str] = []
    conn = sqlite_backend._conn_or_raise()
    trace_conn: Any = conn
    await trace_conn.set_trace_callback(statements.append)

    try:
        await sqlite_backend.upsert_batch(batch, {}, {})
    finally:
        await trace_conn.set_trace_callback(None)

    fts_writes = [
        statement
        for statement in statements
        if "entities_fts" in statement and statement.lstrip().startswith(("DELETE", "INSERT"))
    ]
    assert fts_writes == []


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
    assert primary["metadata"]["merged_people"] == [
        {
            "id": slack_id,
            "title": "Simon",
            "platform_entity_id": "slack:T1/U1",
        },
        {
            "id": discord_id,
            "title": "simon",
            "platform_entity_id": "discord:D1",
        },
    ]

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
        order_by="observed_at",
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

    await upsert_batch(
        EntityBatch(
            persons=[
                PersonRecord(
                    platform="slack",
                    platform_user_id="T1/U2",
                    platform_username="simon.wade.alt",
                    display_name="Simon Wade (alternate)",
                )
            ]
        )
    )
    alternate_id = await sqlite_backend._fetchval(
        "SELECT id FROM entities WHERE platform_entity_id = ?",
        ["slack:T1/U2"],
    )
    await unify_persons(primary_id, [alternate_id])
    merged_primary = await sqlite_backend.get_entity_by_id(primary_id)
    assert merged_primary is not None
    assert [person["id"] for person in merged_primary["metadata"]["merged_people"]] == [
        slack_id,
        discord_id,
        alternate_id,
    ]
