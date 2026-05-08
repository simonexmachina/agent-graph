"""Discord connector (bot token auth)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from agentgraph.connectors.base import (
    BaseConnector,
    EdgeRecord,
    EntityBatch,
    EntityRecord,
    FetchPolicy,
    PersonRecord,
    ResourceType,
)
from agentgraph.graph.upsert import upsert_batch
from agentgraph_connector_discord.auth import load_discord_creds

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"
_STALE_AFTER = 5 * 60  # 5 minutes
_MAX_RETRIES = 3

# Module-level user cache so repeated syncs don't re-fetch the same users
_user_cache: dict[str, PersonRecord] = {}


def _get_headers() -> dict[str, str]:
    creds = load_discord_creds()
    return {"Authorization": f"Bot {creds.bot_token}"}


async def _api_get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    for _attempt in range(_MAX_RETRIES):
        resp = await client.get(
            f"{DISCORD_API}{path}",
            headers=_get_headers(),
            params=params,
            timeout=30,
        )
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "1"))
            is_global = resp.headers.get("X-RateLimit-Global") == "true"
            logger.warning(
                "Discord rate limited%s on %s — sleeping %.1fs",
                " (global)" if is_global else "",
                path,
                retry_after,
            )
            await asyncio.sleep(retry_after)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Discord API {path} still rate-limited after {_MAX_RETRIES} retries")


def _snowflake_to_dt(snowflake: str) -> datetime:
    """Convert a Discord snowflake ID to a UTC datetime."""
    ts_ms = (int(snowflake) >> 22) + 1420070400000
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC)


def _snowflake_after(dt: datetime) -> str:
    """Return the smallest snowflake ID that is strictly after dt."""
    ts_ms = int(dt.timestamp() * 1000) - 1420070400000
    return str(max(ts_ms, 0) << 22)


async def refresh_attachment_urls(
    channel_id: str,
    message_id: str,
    stored_json: str,
) -> str:
    """Return attachments JSON with fresh CDN URLs from Discord.

    Uses POST /attachments/refresh-urls — the purpose-built Discord
    endpoint for renewing expiring signed CDN tokens. Discord only issues
    new tokens once the current ones have expired; while still valid the
    same URL is returned unchanged, which is correct behaviour.

    Falls back to stored_json on missing credentials or any API error.
    channel_id and message_id are accepted for interface compatibility but
    are not used by this endpoint (it operates on the URLs directly).
    """
    import json as _json

    try:
        token = load_discord_creds().bot_token
    except Exception:
        return stored_json

    try:
        attachments: list[dict[str, Any]] = _json.loads(stored_json)
        urls = [a["url"] for a in attachments if a.get("url")]
        if not urls:
            return stored_json

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{DISCORD_API}/attachments/refresh-urls",
                headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                json={"attachment_urls": urls},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

        url_map: dict[str, str] = {
            r["original"]: r["refreshed"]
            for r in data.get("refreshed_urls", [])
        }
        for a in attachments:
            if a.get("url") in url_map:
                a["url"] = url_map[a["url"]]
        return _json.dumps(attachments)
    except Exception as exc:
        logger.debug(
            "discord: could not refresh attachments for %s/%s: %s",
            channel_id, message_id, exc,
        )
        return stored_json


def _parse_mentions(content: str) -> list[str]:
    """Extract <@USER_ID> and <@!USER_ID> user IDs from message content."""
    import re
    return re.findall(r"<@!?(\d+)>", content)


def _extract_attachments(msg: dict[str, Any]) -> str | None:
    """Return attachments as a JSON string for storage in scalar metadata, or None if none."""
    import json
    result: list[dict[str, Any]] = []
    for a in msg.get("attachments", []):
        url: str = a.get("url", "")
        if not url:
            continue
        entry: dict[str, Any] = {"url": url, "filename": a.get("filename", "")}
        content_type: str = a.get("content_type", "")
        if content_type:
            entry["content_type"] = content_type
        width = a.get("width")
        height = a.get("height")
        if width and height:
            entry["width"] = width
            entry["height"] = height
        result.append(entry)
    return json.dumps(result) if result else None


class DiscordConnector(BaseConnector):
    source = "discord"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)
    poll_interval: timedelta | None = timedelta(minutes=5)  # type: ignore[assignment]
    auth_label = "discord"
    auth_description = "Discord (bot token)"
    onboard_prompt = "Set up Discord?"

    @classmethod
    def run_auth_flow(cls) -> None:
        from agentgraph_connector_discord.auth import run_token_flow
        run_token_flow()

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        try:
            return load_discord_creds().bot_user_id
        except Exception:
            return None

    def can_handle(self, url: str) -> bool:
        return "discord.com/channels/" in url

    async def fetch(self, resource_type: ResourceType, resource_id: str, meta: dict[str, str] | None = None) -> EntityBatch:
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            logger.debug("discord/%s is fresh — updating last_accessed only", resource_id)
            await _touch_last_accessed(resource_id)
            return EntityBatch()

        after_snowflake: str | None = None
        if decision == FetchPolicy.INCREMENTAL and last_sync:
            after_snowflake = _snowflake_after(last_sync)

        is_dm = resource_type == "dm"
        logger.info("Fetching Discord %s %s (policy=%s)", resource_type, resource_id, decision)
        batch = await _fetch_channel(resource_id, after_snowflake=after_snowflake, is_dm=is_dm)
        await upsert_batch(batch)
        return batch

    async def poll(self, cursor: dict[str, Any]) -> tuple[EntityBatch, dict[str, Any]]:
        from agentgraph_connector_slack import _get_known_channels

        channel_rows = await _get_known_channels("discord")
        combined = EntityBatch()
        for channel_id, synced_at in channel_rows:
            after_snowflake = _snowflake_after(synced_at) if synced_at else None
            try:
                batch = await _fetch_channel(channel_id, after_snowflake=after_snowflake)
                combined.entities.extend(batch.entities)
                combined.persons.extend(batch.persons)
                combined.edges.extend(batch.edges)
            except Exception:
                logger.exception("discord poll: failed to fetch channel %s", channel_id)
        return combined, cursor


async def _touch_last_accessed(channel_id: str) -> None:
    from agentgraph.core.context import get_backend

    await get_backend().upsert_stub_entity("Channel", "discord", channel_id)


async def _fetch_user(
    client: httpx.AsyncClient,
    user_id: str,
    seen_users: dict[str, PersonRecord],
) -> PersonRecord | None:
    if user_id in seen_users:
        return seen_users[user_id]
    if user_id in _user_cache:
        seen_users[user_id] = _user_cache[user_id]
        return _user_cache[user_id]
    try:
        data = await _api_get(client, f"/users/{user_id}")
        username = data.get("username", "")
        global_name = data.get("global_name") or username
        person = PersonRecord(
            platform="discord",
            platform_user_id=user_id,
            platform_username=username,
            display_name=global_name or None,
            # Discord bots cannot access user emails
        )
        seen_users[user_id] = person
        _user_cache[user_id] = person
        return person
    except Exception as exc:
        logger.debug("Could not fetch Discord user %s: %s", user_id, exc)
        return None


async def _fetch_thread_messages(
    client: httpx.AsyncClient,
    thread_id: str,
    parent_channel_id: str,
    parent_message_id: str,
    entities: list[EntityRecord],
    edges: list[EdgeRecord],
    seen_users: dict[str, PersonRecord],
    persons: list[PersonRecord],
    after_snowflake: str | None,
    guild_id: str = "",
) -> None:
    """Fetch messages in a Discord thread (threads are channels in Discord API)."""
    try:
        params: dict[str, Any] = {"limit": 100}
        if after_snowflake:
            params["after"] = after_snowflake

        messages = await _api_get(client, f"/channels/{thread_id}/messages", **params)
    except Exception as exc:
        logger.warning("Could not fetch thread %s: %s", thread_id, exc)
        return

    for msg in messages:
        msg_id: str = msg.get("id", "")
        content: str = msg.get("content", "")
        author: dict[str, Any] = msg.get("author", {})
        user_id: str = author.get("id", "")

        if not msg_id:
            continue

        attachments_json = _extract_attachments(msg)
        meta: dict[str, Any] = {"channel_id": parent_channel_id, "thread_id": thread_id, "message_id": msg_id}
        if guild_id:
            meta["web_url"] = f"https://discord.com/channels/{guild_id}/{parent_channel_id}/{msg_id}"
        if attachments_json:
            meta["attachments"] = attachments_json

        entities.append(EntityRecord(
            entity_type="Message",
            platform="discord",
            platform_entity_id=f"{thread_id}:{msg_id}",
            content=content,
            created_at=_snowflake_to_dt(msg_id),
            updated_at=_snowflake_to_dt(msg_id),
            metadata=meta,
        ))

        edges.append(EdgeRecord(
            edge_type="replied_to",
            source_platform_entity_id=f"{thread_id}:{msg_id}",
            target_platform_entity_id=f"{parent_channel_id}:{parent_message_id}",
            platform="discord",
        ))
        edges.append(EdgeRecord(
            edge_type="posted_in",
            source_platform_entity_id=f"{thread_id}:{msg_id}",
            target_platform_entity_id=parent_channel_id,
            platform="discord",
        ))

        if user_id:
            person = await _fetch_user(client, user_id, seen_users)
            if person and person not in persons:
                persons.append(person)
            edges.append(EdgeRecord(
                edge_type="authored",
                source_platform_user_id=user_id,
                target_platform_entity_id=f"{thread_id}:{msg_id}",
                platform="discord",
            ))

        for mentioned_id in _parse_mentions(content):
            person = await _fetch_user(client, mentioned_id, seen_users)
            if person and person not in persons:
                persons.append(person)
            edges.append(EdgeRecord(
                edge_type="mentions",
                source_platform_entity_id=f"{thread_id}:{msg_id}",
                target_platform_user_id=mentioned_id,
                platform="discord",
            ))


async def _fetch_channel(
    channel_id: str,
    after_snowflake: str | None = None,
    is_dm: bool = False,
) -> EntityBatch:
    entities: list[EntityRecord] = []
    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []
    seen_users: dict[str, PersonRecord] = {}

    async with httpx.AsyncClient(timeout=30) as client:
        # Channel entity
        try:
            channel_info = await _api_get(client, f"/channels/{channel_id}")
        except Exception as exc:
            logger.error("Could not fetch Discord channel %s: %s", channel_id, exc)
            return EntityBatch()

        guild_id = channel_info.get("guild_id", "")
        channel_type: int = channel_info.get("type", 0)

        if channel_type in (1, 3):  # 1 = DM, 3 = Group DM
            recipients: list[dict[str, Any]] = channel_info.get("recipients", [])
            if channel_type == 3 and channel_info.get("name"):
                channel_name = channel_info["name"]
            elif recipients:
                channel_name = ", ".join(r.get("username", r.get("id", "")) for r in recipients)
            else:
                channel_name = channel_id
            # Emit Person records for DM participants from channel metadata
            for recipient in recipients:
                user_id: str = recipient.get("id", "")
                if not user_id or user_id in seen_users:
                    continue
                username = recipient.get("username", "")
                global_name = recipient.get("global_name") or username
                person = PersonRecord(
                    platform="discord",
                    platform_user_id=user_id,
                    platform_username=username,
                    display_name=global_name or None,
                )
                seen_users[user_id] = person
                _user_cache[user_id] = person
                persons.append(person)
                edges.append(EdgeRecord(
                    edge_type="participated_in",
                    source_platform_user_id=user_id,
                    target_platform_entity_id=channel_id,
                    platform="discord",
                ))
        else:
            channel_name = channel_info.get("name", channel_id)

        channel_meta: dict[str, Any] = {}
        if guild_id:
            channel_meta["guild_id"] = guild_id
            channel_meta["web_url"] = f"https://discord.com/channels/{guild_id}/{channel_id}"
        entities.append(EntityRecord(
            entity_type="Channel",
            platform="discord",
            platform_entity_id=channel_id,
            title=f"#{channel_name}",
            updated_at=datetime.now(UTC),
            metadata=channel_meta,
        ))

        # Fetch messages (Discord returns newest-first; reverse for chronological)
        params: dict[str, Any] = {"limit": 100}
        if after_snowflake:
            params["after"] = after_snowflake

        try:
            messages = await _api_get(client, f"/channels/{channel_id}/messages", **params)
        except Exception as exc:
            logger.error("Could not fetch messages for Discord channel %s: %s", channel_id, exc)
            return EntityBatch(entities=entities)

        for msg in messages:
            msg_id: str = msg.get("id", "")
            content: str = msg.get("content", "")
            author: dict[str, Any] = msg.get("author", {})
            user_id: str = author.get("id", "")
            thread: dict[str, Any] | None = msg.get("thread")

            if not msg_id:
                continue

            attachments_json = _extract_attachments(msg)
            meta: dict[str, Any] = {"channel_id": channel_id, "message_id": msg_id, "guild_id": guild_id}
            if guild_id:
                meta["web_url"] = f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
            if attachments_json:
                meta["attachments"] = attachments_json

            entities.append(EntityRecord(
                entity_type="Message",
                platform="discord",
                platform_entity_id=f"{channel_id}:{msg_id}",
                content=content,
                created_at=_snowflake_to_dt(msg_id),
                updated_at=_snowflake_to_dt(msg_id),
                metadata=meta,
            ))

            edges.append(EdgeRecord(
                edge_type="posted_in",
                source_platform_entity_id=f"{channel_id}:{msg_id}",
                target_platform_entity_id=channel_id,
                platform="discord",
            ))

            if user_id:
                person = await _fetch_user(client, user_id, seen_users)
                if person and person not in persons:
                    persons.append(person)
                edges.append(EdgeRecord(
                    edge_type="authored",
                    source_platform_user_id=user_id,
                    target_platform_entity_id=f"{channel_id}:{msg_id}",
                    platform="discord",
                ))

            for mentioned_id in _parse_mentions(content):
                person = await _fetch_user(client, mentioned_id, seen_users)
                if person and person not in persons:
                    persons.append(person)
                edges.append(EdgeRecord(
                    edge_type="mentions",
                    source_platform_entity_id=f"{channel_id}:{msg_id}",
                    target_platform_user_id=mentioned_id,
                    platform="discord",
                ))

            # Fetch thread replies if this message spawned a thread
            if thread:
                thread_id: str = thread.get("id", "")
                if thread_id:
                    await _fetch_thread_messages(
                        client, thread_id, channel_id, msg_id,
                        entities, edges, seen_users, persons, after_snowflake,
                        guild_id=guild_id,
                    )

    batch = EntityBatch(entities=entities, persons=persons, edges=edges)
    for entity in batch.entities[:]:
        batch.add_stubs_from(entity)
    return batch
