"""Browser observation handling and observation-duration accounting."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from agentgraph.connectors.base import ResourceType, ResourceUnavailableError
from agentgraph.server.router import classify_observation_url

logger = logging.getLogger(__name__)


class ObservationFetchError(RuntimeError):
    """A connector could not hydrate the resource for an observation."""


_inflight_observations: dict[str, asyncio.Task[dict[str, Any]]] = {}


def _forget_inflight_observation(
    observation_id: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    if _inflight_observations.get(observation_id) is task:
        _inflight_observations.pop(observation_id, None)
    if not task.cancelled():
        task.exception()


async def record_observation(
    url: str,
    observation_duration_ms: int,
    observation_id: str,
    observed: bool,
    meta: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Record either a new observation or a duration-only update."""
    ref = await classify_observation_url(url, meta=meta)
    if ref is None:
        logger.debug("report-observation: unrecognised URL %s", url)
        return {"status": "ignored", "reason": "unrecognised URL"}

    from agentgraph.core.context import get_backend

    try:
        backend = get_backend()
        if not observed:
            await backend.increment_observation_duration(
                ref.source, ref.resource_id, observation_duration_ms
            )
            if observation_duration_ms > 0:
                await _notify_observation(
                    source=ref.source,
                    resource_id=ref.resource_id,
                    resource_type=ref.resource_type,
                    url=url,
                    observation_duration_ms=observation_duration_ms,
                    meta=meta,
                )
            logger.debug(
                "Recorded observation-duration update: +%dms for %s %s/%s (observation_id=%s)",
                observation_duration_ms,
                ref.source,
                ref.resource_type,
                ref.resource_id,
                observation_id,
            )
            return {
                "status": "accepted",
                "source": ref.source,
                "resource_type": ref.resource_type,
                "observation_created": False,
            }

        if await backend.observation_exists(observation_id):
            return {
                "status": "accepted",
                "source": ref.source,
                "resource_type": ref.resource_type,
                "observation_created": False,
            }

        task = _inflight_observations.get(observation_id)
        owns_task = task is None
        if task is None:
            fetch_meta = dict(meta or {})
            fetch_meta.update(ref.fetch_meta or {})
            logger.info(
                "New observation %s: fetching %s %s/%s",
                observation_id,
                ref.source,
                ref.resource_type,
                ref.resource_id,
            )
            task = asyncio.create_task(
                _fetch_and_record_observation(
                    source=ref.source,
                    resource_type=ref.resource_type,
                    resource_id=ref.resource_id,
                    observation_id=observation_id,
                    url=url,
                    observation_duration_ms=observation_duration_ms,
                    meta=fetch_meta or None,
                )
            )
            _inflight_observations[observation_id] = task
            task.add_done_callback(
                lambda completed, oid=observation_id: _forget_inflight_observation(oid, completed)
            )

        result = await asyncio.shield(task)

        return {
            **result,
            "observation_created": bool(result["observation_created"] and owns_task),
        }
    except ResourceUnavailableError as exc:
        logger.info(
            "Ignoring observation for unavailable %s %s/%s: %s",
            ref.source,
            ref.resource_type,
            ref.resource_id,
            exc,
        )
        return {"status": "ignored", "reason": "resource unavailable"}
    except ObservationFetchError:
        raise
    except Exception:
        logger.exception("Failed to record observation duration for %s", url)
        return {"status": "error", "reason": "internal backend error"}


async def _fetch_and_record_observation(
    *,
    source: str,
    resource_type: ResourceType,
    resource_id: str,
    observation_id: str,
    url: str,
    observation_duration_ms: int,
    meta: dict[str, str] | None,
) -> dict[str, Any]:
    counts = await _dispatch(source, resource_type, resource_id, meta)

    from agentgraph.core.context import get_backend

    backend = get_backend()
    entity = await backend.get_entity_by_platform(source, resource_id)
    if entity is None:
        raise ObservationFetchError(
            f"Connector fetch completed without persisting {source} {resource_type}/{resource_id}"
        )

    observation_created = await backend.record_observation_once(
        source,
        resource_id,
        observation_id,
        url,
        observation_duration_ms,
    )
    if observation_created and observation_duration_ms > 0:
        await _notify_observation(
            source=source,
            resource_id=resource_id,
            resource_type=resource_type,
            url=url,
            observation_duration_ms=observation_duration_ms,
            meta=meta,
        )
    return {
        "status": "accepted",
        "source": source,
        "resource_type": resource_type,
        "observation_created": observation_created,
        "fetch": counts,
    }


async def _notify_observation(
    *,
    source: str,
    resource_id: str,
    resource_type: ResourceType,
    url: str,
    observation_duration_ms: int,
    meta: dict[str, str] | None,
) -> None:
    from agentgraph.connectors.feed import (
        ObservationMutation,
        mutation_target_from_reference,
        notify_feed_connectors,
    )

    await notify_feed_connectors(
        ObservationMutation(
            target=mutation_target_from_reference(
                platform=source,
                platform_entity_id=resource_id,
                resource_type=resource_type,
                url=url,
            ),
            observation_duration_ms=observation_duration_ms,
            meta=meta,
        )
    )


async def _dispatch(
    source: str,
    resource_type: ResourceType,
    resource_id: str,
    meta: dict[str, str] | None = None,
) -> dict[str, int]:
    from agentgraph.connectors.registry import get_connector

    connector = get_connector(source)
    if connector is None:
        raise ObservationFetchError(f"No connector registered for source '{source}'")
    try:
        logger.info("Fetching %s/%s/%s", source, resource_type, resource_id)
        batch = await connector.fetch(
            resource_type=resource_type, resource_id=resource_id, meta=meta
        )
        if batch.has_writes():
            from agentgraph.graph.upsert import upsert_batch

            await upsert_batch(batch)
        logger.info(
            "Fetch complete %s/%s/%s — %d entities, %d persons, %d edges",
            source,
            resource_type,
            resource_id,
            len(batch.entities),
            len(batch.persons),
            len(batch.edges),
        )
        return {
            "entities": len(batch.entities),
            "metadata_patches": len(batch.metadata_patches),
            "persons": len(batch.persons),
            "edges": len(batch.edges),
        }
    except (ObservationFetchError, ResourceUnavailableError):
        raise
    except Exception as exc:
        logger.exception("Connector fetch failed: %s/%s/%s", source, resource_type, resource_id)
        raise ObservationFetchError(
            f"Connector fetch failed for {source} {resource_type}/{resource_id}"
        ) from exc
