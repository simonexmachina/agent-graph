"""Base connector interface and shared batch types."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

# All resource_type values understood by the connector layer.
# Each value maps to a distinct fetch strategy within a connector.
ResourceType = Literal["channel", "dm", "document", "folder", "message", "spreadsheet", "thread"]

# All valid entity_type values stored in the DB.
ENTITY_TYPES: tuple[str, ...] = (
    "Channel",
    "Document",
    "Folder",
    "Message",
    "Person",
    "Spreadsheet",
    "Email",
)

# Broad URL extractor — classify_url does fine-grained matching
_URL_RE = re.compile(r"https?://\S+")

# Maps ResourceType values to entity_type strings stored in the DB
RESOURCE_TYPE_TO_ENTITY_TYPE: dict[str, str] = {
    "channel":     "Channel",
    "dm":          "Channel",
    "document":    "Document",
    "folder":      "Folder",
    "message":     "Message",
    "spreadsheet": "Spreadsheet",
    "thread":      "Email",
}


@dataclass(frozen=True)
class SourceReference:
    source: str
    resource_type: ResourceType
    resource_id: str
    fetch_meta: dict[str, str] | None = None


@dataclass(frozen=True)
class ConnectorCommandEffects:
    """Side effects requested after a connector command succeeds."""

    poll: bool = False


class PersonRecord(BaseModel):
    platform: str
    platform_user_id: str
    platform_username: str | None = None
    canonical_email: str | None = None
    display_name: str | None = None


class EntityRecord(BaseModel):
    entity_type: str          # 'Message' | 'Document' | 'Channel' | 'Task'
    platform: str
    platform_entity_id: str
    title: str | None = None
    content: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, str | int | float | bool | None] = {}
    is_stub: bool = False     # True → placeholder pending a full fetch; preserves synced_at=NULL


class EdgeRecord(BaseModel):
    edge_type: str            # 'authored' | 'posted_in' | 'replied_to' | 'mentions'
    source_platform_entity_id: str | None = None
    source_platform_user_id: str | None = None
    target_platform_entity_id: str | None = None
    target_platform_user_id: str | None = None
    platform: str
    properties: dict[str, str | int | float | bool | None] = {}


class EntityBatch(BaseModel):
    entities: list[EntityRecord] = []
    edges: list[EdgeRecord] = []
    persons: list[PersonRecord] = []

    def add_stubs_from(self, entity: EntityRecord) -> None:
        """Scan entity content for recognisable URLs and append stub EntityRecords and
        'references' EdgeRecords to this batch.

        Connectors call this after building each content-bearing entity so that
        linked resources from other platforms are visible in the graph before they
        are fetched.  Stub entities are inserted with synced_at=NULL so the
        relevant connector will do a full fetch when the resource is next visited.
        """
        if not entity.content:
            return
        from agentgraph.server.router import classify_url

        seen: set[str] = set()
        for raw_url in _URL_RE.findall(entity.content):
            ref = classify_url(raw_url)
            if ref is None:
                continue
            key = f"{ref.source}/{ref.resource_id}"
            if key in seen:
                continue
            # Skip self-references (e.g. a doc linking to itself)
            if ref.source == entity.platform and ref.resource_id == entity.platform_entity_id:
                continue
            seen.add(key)
            self.entities.append(EntityRecord(
                entity_type=RESOURCE_TYPE_TO_ENTITY_TYPE[ref.resource_type],
                platform=ref.source,
                platform_entity_id=ref.resource_id,
                is_stub=True,
            ))
            self.edges.append(EdgeRecord(
                edge_type="references",
                source_platform_entity_id=entity.platform_entity_id,
                target_platform_entity_id=ref.resource_id,
                platform="cross",
            ))


async def get_known_channel_syncs(
    platform: str,
    account_id: str | None = None,
) -> list[tuple[str, datetime | None]]:
    """Return (platform_entity_id, synced_at) for known Channel entities on a platform."""
    from agentgraph.core.context import get_backend

    entities = await get_backend().list_entities(
        entity_types=["Channel"],
        platform=platform,
        since=None,
        limit=10_000,
    )
    result: list[tuple[str, datetime | None]] = []
    for entity in entities:
        metadata = entity.get("metadata")
        if (
            account_id
            and isinstance(metadata, dict)
            and metadata.get("account_id") not in (None, account_id)
        ):
            continue

        platform_entity_id = entity.get("platform_entity_id")
        if not isinstance(platform_entity_id, str):
            continue

        synced_at_value = entity.get("synced_at")
        synced_at = (
            datetime.fromisoformat(synced_at_value)
            if isinstance(synced_at_value, str) and synced_at_value
            else None
        )
        result.append((platform_entity_id, synced_at))
    return result


class ConnectorAccount(BaseModel):
    account_id: str
    label: str
    auth_group: str
    source: str
    user_id: str | None = None
    workspace_id: str | None = None
    email: str | None = None
    auth_method: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)



class FetchPolicy:
    """Encapsulates refresh policy decisions for a resource."""

    FIRST_VISIT = "first_visit"
    INCREMENTAL = "incremental"
    FRESH = "fresh"

    def __init__(self, stale_after_seconds: int) -> None:
        self.stale_after = timedelta(seconds=stale_after_seconds)

    def decide(self, last_synced_at: datetime | None) -> str:
        """
        Return FIRST_VISIT, INCREMENTAL, or FRESH based on last sync time.
        - FIRST_VISIT: never synced
        - INCREMENTAL: synced but data is stale
        - FRESH: synced recently, only update last_accessed
        """
        if last_synced_at is None:
            return self.FIRST_VISIT
        age = datetime.now(UTC) - last_synced_at
        if age > self.stale_after:
            return self.INCREMENTAL
        return self.FRESH


class BaseConnector(ABC):
    source: ClassVar[str]           # platform name, e.g. "slack" — must be set by subclass
    fetch_policy: ClassVar[FetchPolicy]  # staleness policy — must be set by subclass
    is_generic_url_fallback: ClassVar[bool] = False
    """True for broad fallback connectors that should not claim URLs during discovery."""

    poll_interval: ClassVar[timedelta | None] = None
    """Interval between background poll() calls. None disables polling for this connector."""

    poll_delegates: ClassVar[list[str]] = []
    """Connector sources refreshed indirectly by this connector's poll() implementation."""

    url_patterns: ClassVar[list[str]] = []
    """Chrome match-pattern strings (e.g. "https://mail.google.com/*") that identify URLs
    this connector can handle. Used by the browser extension to decide which tabs to watch."""

    # Auth integration — override in subclasses that support interactive auth.
    # auth_label deduplicates across connectors that share credentials (e.g. all Google connectors).
    auth_label: ClassVar[str | None] = None
    auth_description: ClassVar[str | None] = None
    onboard_prompt: ClassVar[str | None] = None
    appears_in_auth_status: ClassVar[bool] = True
    """True for connectors backed by user/provider credentials.

    Connectors that only need configuration, or no setup at all, should leave
    `agentgraph auth status` to real authentication providers.
    """

    @classmethod
    def run_auth_flow(
        cls,
        account_id: str | None = None,
        add: bool = False,
        args: list[str] | None = None,
    ) -> None:
        """Run the interactive authentication flow for this connector."""
        raise NotImplementedError(f"{cls.__name__} does not have an auth flow")

    @classmethod
    def run_auth_flow_with_args(
        cls,
        args: list[str],
        account_id: str | None = None,
        add: bool = False,
    ) -> None:
        """Parse connector-owned auth arguments and run authentication."""
        cls.run_auth_flow(account_id=account_id, add=add, args=args)

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        """Return a display string for the currently authenticated user, or None."""
        return None

    @classmethod
    def list_accounts(cls) -> list[ConnectorAccount]:
        """Return the authenticated accounts known to this connector."""
        user = cls.get_authenticated_user()
        if user is None:
            return []
        return [ConnectorAccount(
            account_id=cls.source,
            label=user,
            auth_group=cls.auth_label or cls.source,
            source=cls.source,
            user_id=user,
            email=user if "@" in user else None,
        )]

    @classmethod
    async def verify_auth(cls, account_id: str | None = None) -> tuple[str, str | None]:
        """Check whether stored credentials are valid.

        Returns a (status, detail) tuple where status is one of:
          - "ok": credentials present and (where verified) accepted by the platform
          - "missing": no credentials stored
          - "invalid": credentials present but rejected by the platform

        The default implementation only checks credential presence via
        get_authenticated_user(). Override in subclasses that want to make a
        live API call (e.g. /users/@me) to detect token resets or expiry.
        """
        user = cls.get_authenticated_user()
        if user is None:
            return ("missing", None)
        return ("ok", user)

    @classmethod
    def run_cli_command(cls, args: list[str]) -> dict[str, Any]:
        """Run a connector-owned CLI command.

        Core dispatches to this hook generically via `agentgraph connector <source> ...`.
        Connectors own their command names, argument parsing, and behaviour.
        """
        _ = args
        raise NotImplementedError(f"{cls.source} does not expose connector commands")

    @classmethod
    def cli_help(cls) -> str:
        """Return help text for connector-owned CLI commands."""
        return f"{cls.source} does not expose connector commands"

    @classmethod
    def format_cli_result(cls, result: dict[str, Any]) -> str:
        """Return human-readable output for a connector-owned CLI command result."""
        import json

        return json.dumps(result, indent=2, default=str)

    @classmethod
    def command_effects(
        cls,
        args: list[str],
        result: dict[str, Any],
    ) -> ConnectorCommandEffects:
        """Return side effects for core to run after a command succeeds."""
        _ = (args, result)
        return ConnectorCommandEffects()

    def normalise_fetch_id(
        self, resource_id: str, entity_type: str
    ) -> tuple[str, ResourceType]:
        """Map a stored resource_id + entity_type to the (id, resource_type) that fetch() expects.

        The default maps entity_type to ResourceType using the standard table and
        returns resource_id unchanged. Connectors override this when their stored IDs
        differ from their fetchable IDs (e.g. Discord message IDs encode the channel).
        """
        resource_type_map: dict[str, ResourceType] = {
            "Document": "document",
            "Folder": "folder",
            "Spreadsheet": "spreadsheet",
            "Channel": "channel",
            "Message": "message",
            "Email": "thread",
        }
        return resource_id, resource_type_map.get(entity_type, "document")  # type: ignore[return-value]

    @classmethod
    def current_user_id(cls) -> str | None:
        """Return the canonical identifier for the authenticated user on this platform.

        The value returned must match the platform_entity_id stored on the user's
        Person entity (i.e. canonical_email, or "platform:user_id" if no email).
        Used by --mine filtering. Returns None if not authenticated or not applicable.
        """
        return None

    @classmethod
    def current_user_ids(cls) -> list[str]:
        """Return all canonical identifiers for authenticated users on this platform."""
        user_id = cls.current_user_id()
        return [user_id] if user_id else []

    def poll_account_ids(self) -> list[str | None]:
        """Return the account IDs that should receive background polling."""
        accounts = type(self).list_accounts()
        return [account.account_id for account in accounts] or [None]

    @abstractmethod
    def can_handle(self, url: str) -> bool: ...

    def resolve_url(self, url: str) -> SourceReference | None:
        """Return the fetchable resource behind a URL, if this connector owns it."""
        _ = url
        return None

    async def resolve_observation_url(self, url: str) -> SourceReference | None:
        """Resolve a URL observed by the browser extension.

        Connectors can override this when resolution requires an async lookup or
        fetch metadata that must accompany a targeted fetch. The default keeps
        existing synchronous URL resolvers usable for observations.
        """
        return self.resolve_url(url)

    async def observation_url_patterns(self) -> list[str]:
        """Return browser observation patterns, including connector-derived ones."""
        return self.url_patterns

    @abstractmethod
    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch: ...

    async def ingest(self, account_id: str | None = None) -> EntityBatch:
        """Run a one-shot bulk ingest of all available historical data for this connector.

        Override in connectors that support a full-history sweep beyond what poll() covers
        on first run (e.g. fetching all labels, not just inbox). The default no-ops so that
        connectors which don't need this remain unchanged.
        """
        return EntityBatch()

    async def poll(
        self,
        cursor: dict[str, Any],
        account_id: str | None = None,
    ) -> tuple[EntityBatch, dict[str, Any]]:
        """Fetch all changes since cursor for background sync.

        cursor is {} on first call. Return (batch, updated_cursor).
        The SyncEngine persists the cursor between calls and upserts the returned batch.
        Connectors that handle upserting internally (e.g. by calling fetch()) should
        return an empty EntityBatch.
        """
        return EntityBatch(), cursor

    def entity_url(self, platform_entity_id: str) -> str | None:
        """Return the canonical web URL for an entity given its platform_entity_id.

        Used to populate metadata.web_url for entities that don't store it at
        ingest time. Return None if the URL cannot be derived from the ID alone
        (e.g. it requires metadata like guild_id or team_id).
        """
        return None

    async def download(
        self,
        resource_type: ResourceType,
        resource_id: str,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Download an entity's source file using the connector's stored auth.

        Connectors that expose downloadable files should override this method
        and return metadata including the written path.
        """
        raise NotImplementedError(f"{self.source} does not support authenticated downloads")

    async def enrich_results(self, entities: list[dict[str, Any]]) -> None:
        """Mutate query/search result entities with connector-owned presentation fixes.

        This hook lets connectors refresh short-lived metadata or add derived
        fields before entities are returned to clients. The default no-ops.
        """
        _ = entities

    async def last_synced_at(self, resource_id: str) -> datetime | None:
        """Return the most recent synced_at for a platform entity, or None."""
        from agentgraph.core.context import get_backend

        return await get_backend().get_last_synced_at(self.source, resource_id)
