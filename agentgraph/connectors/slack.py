"""Slack connector (cookie token auth)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from agentgraph.auth.credentials import load as load_creds
from agentgraph.connectors.base import (
    BaseConnector,
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
)
from agentgraph.graph.upsert import upsert_batch

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"
_STALE_AFTER = 5 * 60  # 5 minutes
_PADDING_MESSAGES = 20  # messages to fetch on first visit as immediate context


def _get_headers() -> dict[str, str]:
    stored = load_creds()
    if stored.slack is None:
        raise RuntimeError("Slack credentials not configured. Run: agentgraph auth slack")
    return {
        "Authorization": f"Bearer {stored.slack.xoxc_token}",
        "Cookie": f"d={stored.slack.d_cookie}",
        "Content-Type": "application/json",
    }


async def _api_get(client: httpx.AsyncClient, method: str, **params: Any) -> dict[str, Any]:
    resp = await client.get(
        f"{SLACK_API}/{method}",
        headers=_get_headers(),
        params=params,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Slack API error on {method}: {data.get('error', 'unknown')}")
    return data


async def _fetch_channel_info(client: httpx.AsyncClient, channel_id: str) -> dict[str, Any]:
    data = await _api_get(client, "conversations.info", channel=channel_id)
    return data.get("channel", {})  # type: ignore[return-value]


async def _fetch_user(client: httpx.AsyncClient, user_id: str) -> dict[str, Any]:
    data = await _api_get(client, "users.info", user=user_id)
    return data.get("user", {})  # type: ignore[return-value]


def _ts_to_dt(ts: str) -> datetime:
    return datetime.fromtimestamp(float(ts), tz=UTC)


def _parse_mentions(text: str) -> list[str]:
    """Extract <@UXXXXXXX> user IDs from message text."""
    import re
    return re.findall(r"<@([A-Z0-9]+)>", text)


class SlackConnector(BaseConnector):
    source = "slack"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)

    def can_handle(self, url: str) -> bool:
        return "app.slack.com" in url

    async def fetch(self, resource_type: str, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            logger.debug("slack/%s is fresh — updating last_accessed only", resource_id)
            await _touch_last_accessed(resource_id)
            return EntityBatch()

        oldest: str | None = None
        if decision == FetchPolicy.INCREMENTAL and last_sync:
            oldest = str(last_sync.timestamp())

        logger.info("Fetching Slack channel %s (policy=%s)", resource_id, decision)
        batch = await _fetch_channel(resource_id, oldest=oldest)
        await upsert_batch(batch)
        return batch


async def _touch_last_accessed(channel_id: str) -> None:
    from agentgraph.db.connection import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:  # type: ignore[attr-defined]
        await conn.execute(  # type: ignore[attr-defined]
            "UPDATE entities SET last_accessed = now() WHERE platform = 'slack' AND platform_entity_id = $1",
            channel_id,
        )


async def _fetch_thread_replies(
    client: httpx.AsyncClient,
    channel_id: str,
    thread_ts: str,
    entities: list[EntityRecord],
    persons: list[PersonRecord],
    edges: list[EdgeRecord],
    seen_users: set[str],
) -> None:
    """Fetch replies to a threaded message and add them to the batch in-place."""
    try:
        data = await _api_get(
            client, "conversations.replies", channel=channel_id, ts=thread_ts
        )
    except Exception as exc:
        logger.warning("Could not fetch replies for %s:%s: %s", channel_id, thread_ts, exc)
        return

    reply_messages: list[dict[str, Any]] = data.get("messages", [])

    for reply in reply_messages:
        ts: str = reply.get("ts", "")
        if not ts or ts == thread_ts:
            continue  # skip the parent message Slack echoes back

        user_id: str = reply.get("user", "")
        text: str = reply.get("text", "")

        entities.append(EntityRecord(
            entity_type="Message",
            platform="slack",
            platform_entity_id=f"{channel_id}:{ts}",
            content=text,
            created_at=_ts_to_dt(ts),
            updated_at=_ts_to_dt(ts),
            metadata={"channel_id": channel_id, "ts": ts, "thread_ts": thread_ts},
        ))

        edges.append(EdgeRecord(
            edge_type="replied_to",
            source_platform_entity_id=f"{channel_id}:{ts}",
            target_platform_entity_id=f"{channel_id}:{thread_ts}",
            platform="slack",
        ))
        edges.append(EdgeRecord(
            edge_type="posted_in",
            source_platform_entity_id=f"{channel_id}:{ts}",
            target_platform_entity_id=channel_id,
            platform="slack",
        ))

        if user_id and user_id not in seen_users:
            seen_users.add(user_id)
            try:
                user_info = await _fetch_user(client, user_id)
                profile = user_info.get("profile", {})
                persons.append(PersonRecord(
                    platform="slack",
                    platform_user_id=user_id,
                    platform_username=user_info.get("name"),
                    canonical_email=profile.get("email") or None,
                    display_name=profile.get("real_name") or None,
                ))
            except Exception:
                logger.debug("Could not fetch user %s", user_id)

        if user_id:
            edges.append(EdgeRecord(
                edge_type="authored",
                source_platform_user_id=user_id,
                target_platform_entity_id=f"{channel_id}:{ts}",
                platform="slack",
            ))

        for mentioned_id in _parse_mentions(text):
            if mentioned_id not in seen_users:
                seen_users.add(mentioned_id)
                try:
                    user_info = await _fetch_user(client, mentioned_id)
                    profile = user_info.get("profile", {})
                    persons.append(PersonRecord(
                        platform="slack",
                        platform_user_id=mentioned_id,
                        platform_username=user_info.get("name"),
                        canonical_email=profile.get("email") or None,
                        display_name=profile.get("real_name") or None,
                    ))
                except Exception:
                    logger.debug("Could not fetch user %s", mentioned_id)
            edges.append(EdgeRecord(
                edge_type="mentions",
                source_platform_entity_id=f"{channel_id}:{ts}",
                target_platform_user_id=mentioned_id,
                platform="slack",
            ))


async def _fetch_channel(channel_id: str, oldest: str | None = None) -> EntityBatch:
    entities: list[EntityRecord] = []
    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []
    seen_users: set[str] = set()

    async with httpx.AsyncClient(timeout=30) as client:
        # Channel entity
        channel_info = await _fetch_channel_info(client, channel_id)
        channel_name = channel_info.get("name", channel_id)

        channel_entity = EntityRecord(
            entity_type="Channel",
            platform="slack",
            platform_entity_id=channel_id,
            title=f"#{channel_name}",
            updated_at=datetime.now(UTC),
        )
        entities.append(channel_entity)

        # Fetch messages
        params: dict[str, Any] = {"channel": channel_id, "limit": 100}
        if oldest:
            params["oldest"] = oldest

        data = await _api_get(client, "conversations.history", **params)
        messages: list[dict[str, Any]] = data.get("messages", [])

        for msg in messages:
            user_id: str = msg.get("user", "")
            ts: str = msg.get("ts", "")
            text: str = msg.get("text", "")
            thread_ts: str | None = msg.get("thread_ts")
            reply_count: int = msg.get("reply_count", 0)

            if not ts:
                continue

            msg_entity = EntityRecord(
                entity_type="Message",
                platform="slack",
                platform_entity_id=f"{channel_id}:{ts}",
                content=text,
                created_at=_ts_to_dt(ts),
                updated_at=_ts_to_dt(ts),
                metadata={"channel_id": channel_id, "ts": ts},
            )
            entities.append(msg_entity)

            # posted_in edge: message → channel
            edges.append(EdgeRecord(
                edge_type="posted_in",
                source_platform_entity_id=f"{channel_id}:{ts}",
                target_platform_entity_id=channel_id,
                platform="slack",
            ))

            # Thread reply edge (this message is itself a reply)
            if thread_ts and thread_ts != ts:
                edges.append(EdgeRecord(
                    edge_type="replied_to",
                    source_platform_entity_id=f"{channel_id}:{ts}",
                    target_platform_entity_id=f"{channel_id}:{thread_ts}",
                    platform="slack",
                ))

            # Author
            if user_id and user_id not in seen_users:
                seen_users.add(user_id)
                user_info = await _fetch_user(client, user_id)
                profile = user_info.get("profile", {})
                persons.append(PersonRecord(
                    platform="slack",
                    platform_user_id=user_id,
                    platform_username=user_info.get("name"),
                    canonical_email=profile.get("email") or None,
                    display_name=profile.get("real_name") or None,
                ))

            if user_id:
                edges.append(EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id=user_id,
                    target_platform_entity_id=f"{channel_id}:{ts}",
                    platform="slack",
                ))

            # Mention edges
            for mentioned_id in _parse_mentions(text):
                if mentioned_id not in seen_users:
                    seen_users.add(mentioned_id)
                    try:
                        user_info = await _fetch_user(client, mentioned_id)
                        profile = user_info.get("profile", {})
                        persons.append(PersonRecord(
                            platform="slack",
                            platform_user_id=mentioned_id,
                            platform_username=user_info.get("name"),
                            canonical_email=profile.get("email") or None,
                            display_name=profile.get("real_name") or None,
                        ))
                    except Exception:
                        logger.debug("Could not fetch user %s", mentioned_id)
                edges.append(EdgeRecord(
                    edge_type="mentions",
                    source_platform_entity_id=f"{channel_id}:{ts}",
                    target_platform_user_id=mentioned_id,
                    platform="slack",
                ))

            # Fetch thread replies for messages that have them
            if reply_count > 0 and not (thread_ts and thread_ts != ts):
                await _fetch_thread_replies(
                    client, channel_id, ts, entities, persons, edges, seen_users
                )

    return EntityBatch(entities=entities, persons=persons, edges=edges)
