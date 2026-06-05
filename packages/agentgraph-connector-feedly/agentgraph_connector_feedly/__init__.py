"""Feedly connector."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from agentgraph.connectors.base import (
    BaseConnector,
    ConnectorAccount,
    EntityBatch,
    FetchPolicy,
    ResourceType,
)
from agentgraph_connector_feedly.auth import (
    collect_stream_preview,
    list_feedly_accounts,
    load_feedly_creds,
    run_token_flow,
    verify_feedly_auth,
)

_STALE_AFTER = 30 * 60


class FeedlyConnector(BaseConnector):
    source = "feedly"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)
    poll_interval: timedelta | None = None  # type: ignore[assignment]
    url_patterns = ["https://feedly.com/*"]
    auth_label = "feedly"
    auth_description = (
        "Feedly streams: API-token access to folders, Boards, and AI Feeds. "
        "This connector currently verifies access and previews configured streams."
    )
    onboard_prompt = "Set up Feedly?"

    @classmethod
    def run_auth_flow(cls, account_id: str | None = None, add: bool = False) -> None:
        run_token_flow(account_id=account_id, add=add)

    @classmethod
    def get_authenticated_user(cls) -> str | None:
        try:
            creds = load_feedly_creds()
        except RuntimeError:
            return None
        return creds.label or "Feedly"

    @classmethod
    def list_accounts(cls) -> list[ConnectorAccount]:
        return [
            ConnectorAccount(
                account_id=str(account["account_id"]),
                label=str(account["label"]),
                auth_group=cls.auth_label or cls.source,
                source=cls.source,
                metadata={
                    "stream_count": str(account.get("stream_count") or "0"),
                },
            )
            for account in list_feedly_accounts()
        ]

    @classmethod
    async def verify_auth(cls, account_id: str | None = None) -> tuple[str, str | None]:
        return await verify_feedly_auth(account_id)

    def can_handle(self, url: str) -> bool:
        return "feedly.com" in url

    async def preview_stream(
        self,
        stream_id: str,
        *,
        account_id: str | None = None,
        count: int = 3,
    ) -> dict[str, Any]:
        return await collect_stream_preview(stream_id, account_id=account_id, count=count)

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
        account_id: str | None = None,
    ) -> EntityBatch:
        _ = (resource_type, resource_id, meta, account_id)
        return EntityBatch()
