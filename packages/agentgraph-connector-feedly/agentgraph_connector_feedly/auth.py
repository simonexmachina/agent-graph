"""Feedly API token credential flow."""

from __future__ import annotations

from typing import Any, cast

import httpx
from pydantic import BaseModel, Field

FEEDLY_API = "https://api.feedly.com/v3"


class FeedlyCredentials(BaseModel):
    access_token: str
    stream_ids: list[str] = Field(default_factory=list)
    account_id: str | None = None
    label: str | None = None


def load_feedly_creds(account_id: str | None = None) -> FeedlyCredentials:
    from agentgraph.auth.credentials import load_platform_account

    data = load_platform_account("feedly", account_id)
    if data is None:
        raise RuntimeError("Feedly credentials not configured. Run: agentgraph auth feedly")
    return FeedlyCredentials(**data)


def list_feedly_accounts() -> list[dict[str, str | None]]:
    from agentgraph.auth.credentials import load_platform_accounts

    results: list[dict[str, str | None]] = []
    for raw in load_platform_accounts("feedly"):
        try:
            creds = FeedlyCredentials(**raw)
        except Exception:
            continue
        account_id = str(raw.get("account_id") or creds.account_id or "feedly")
        label = creds.label or f"{len(creds.stream_ids)} Feedly stream(s)"
        results.append({
            "account_id": account_id,
            "label": label,
            "stream_count": str(len(creds.stream_ids)),
        })
    return results


def _headers(creds: FeedlyCredentials) -> dict[str, str]:
    return {"Authorization": f"Bearer {creds.access_token}"}


async def collect_stream_preview(
    stream_id: str,
    *,
    account_id: str | None = None,
    count: int = 3,
) -> dict[str, Any]:
    """Fetch a small page from a Feedly stream for auth checks and exploration."""
    creds = load_feedly_creds(account_id)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{FEEDLY_API}/streams/contents",
            headers=_headers(creds),
            params={
                "streamID": stream_id,
                "count": str(max(1, min(count, 100))),
            },
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data


async def verify_feedly_auth(account_id: str | None = None) -> tuple[str, str | None]:
    try:
        creds = load_feedly_creds(account_id)
    except RuntimeError:
        return ("missing", None)

    if not creds.stream_ids:
        return ("invalid", "No Feedly stream IDs configured")

    try:
        preview = await collect_stream_preview(creds.stream_ids[0], account_id=account_id, count=1)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code in (401, 403):
            return ("invalid", f"Feedly rejected credentials ({status_code})")
        return ("invalid", f"Feedly API error ({status_code})")
    except Exception as exc:
        return ("invalid", str(exc))

    item_count = len(preview.get("items", [])) if isinstance(preview.get("items"), list) else 0
    return ("ok", f"{len(creds.stream_ids)} stream(s), sample returned {item_count} article(s)")


def run_token_flow(
    account_id: str | None = None,
    add: bool = False,
) -> None:
    import typer

    from agentgraph.auth.credentials import save_platform, upsert_platform_account
    from agentgraph.config import CREDENTIALS_FILE

    typer.echo(
        "\n"
        "Feedly authentication uses an API access token plus one or more stream IDs.\n"
        "Create/copy the token from Feedly's API access page, then copy stream IDs\n"
        "from the Feedly folder, Board, or AI Feed you want AgentGraph to inspect.\n"
    )
    token: str = typer.prompt("Feedly API access token", hide_input=True).strip()
    raw_streams: str = typer.prompt("Feedly stream IDs (comma-separated)").strip()
    stream_ids = [part.strip() for part in raw_streams.split(",") if part.strip()]
    label: str = typer.prompt("Account label", default="Feedly").strip()
    resolved_account_id = account_id or "feedly"

    creds = FeedlyCredentials(
        access_token=token,
        stream_ids=stream_ids,
        account_id=resolved_account_id,
        label=label,
    )
    if not add and account_id is None and not list_feedly_accounts():
        save_platform("feedly", {**creds.model_dump(mode="json"), "account_id": resolved_account_id})
    else:
        upsert_platform_account("feedly", resolved_account_id, creds, make_default=True)

    typer.echo(f"\nFeedly credentials saved to {CREDENTIALS_FILE}")
    if stream_ids:
        typer.echo("Checking configured stream(s)...")
        import asyncio

        async def _check() -> None:
            status, detail = await verify_feedly_auth(resolved_account_id)
            if status == "ok":
                typer.echo(f"Feedly auth verified: {detail}")
                preview = await collect_stream_preview(stream_ids[0], account_id=resolved_account_id, count=3)
                items = preview.get("items", [])
                if isinstance(items, list) and items:
                    typer.echo("Sample articles from first stream:")
                    for item in cast(list[object], items)[:3]:
                        if isinstance(item, dict):
                            item_dict = cast(dict[str, object], item)
                            title = item_dict.get("title") or item_dict.get("id") or "(untitled)"
                            typer.echo(f"  - {title}")
            else:
                typer.echo(f"Feedly auth check failed: {detail or status}")

        asyncio.run(_check())
