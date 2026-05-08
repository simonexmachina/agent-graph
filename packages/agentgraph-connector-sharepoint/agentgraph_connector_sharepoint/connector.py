"""SharePoint and OneDrive connector — fetches documents via Microsoft Graph API."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import base64
import io
import logging
from datetime import datetime
from typing import Any

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

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_STALE_AFTER = 15 * 60

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class SharePointConnector(BaseConnector):
    source = "sharepoint"
    fetch_policy = FetchPolicy(stale_after_seconds=_STALE_AFTER)

    def can_handle(self, url: str) -> bool:
        return ".sharepoint.com/" in url

    async def fetch(
        self,
        resource_type: ResourceType,
        resource_id: str,
        meta: dict[str, str] | None = None,
    ) -> EntityBatch:
        last_sync = await self.last_synced_at(resource_id)
        decision = self.fetch_policy.decide(last_sync)

        if decision == FetchPolicy.FRESH:
            logger.debug("sharepoint/%s is fresh — updating last_accessed only", resource_id)
            await _touch_last_accessed(resource_id)
            return EntityBatch()

        logger.info("Fetching SharePoint document %s (policy=%s)", resource_id, decision)
        batch = await _fetch_item(resource_id)
        await upsert_batch(batch)
        return batch


async def _touch_last_accessed(resource_id: str) -> None:
    from agentgraph.core.context import get_backend

    await get_backend().touch_last_accessed("sharepoint", resource_id)


async def _fetch_item(resource_id: str) -> EntityBatch:
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_item_sync, resource_id)


def _decode_sharing_url(resource_id: str) -> str | None:
    """Decode a u!<base64url> resource_id back to the original sharing URL, or None."""
    if not resource_id.startswith("u!"):
        return None
    encoded = resource_id[2:]
    # Re-add base64 padding
    padding = (4 - len(encoded) % 4) % 4
    try:
        return base64.urlsafe_b64decode(encoded + "=" * padding).decode()
    except Exception:
        return None


def _is_folder_url(url: str) -> bool:
    if "/:f:/" in url:
        return True
    if "AllItems.aspx" not in url:
        return False
    # AllItems.aspx is used for both folder listings AND single-file previews.
    # When the 'id' param has a file extension, it's a file preview — not a folder.
    from urllib.parse import parse_qs, unquote, urlparse
    import os
    params = parse_qs(urlparse(url).query)
    id_param = unquote(params.get("id", [""])[0])
    _, ext = os.path.splitext(id_param)
    return not bool(ext)


def _is_file_preview_url(url: str) -> bool:
    """Return True for AllItems.aspx?id=<path/to/file.ext> (single-file preview)."""
    if "AllItems.aspx" not in url:
        return False
    from urllib.parse import parse_qs, unquote, urlparse
    import os
    params = parse_qs(urlparse(url).query)
    id_param = unquote(params.get("id", [""])[0])
    _, ext = os.path.splitext(id_param)
    return bool(ext)


def _is_sharing_link(url: str) -> bool:
    """Return True for /:x:/ style sharing links; False for server-relative paths."""
    return "/:" in url and ":/" in url


def _fetch_item_sync(resource_id: str) -> EntityBatch:
    sharing_url = _decode_sharing_url(resource_id)

    if sharing_url and _is_folder_url(sharing_url):
        result = _list_folder(sharing_url, resource_id)
        if result is not None:
            return result
        logger.info("Folder listing failed for %s — no cookies configured?", resource_id)
        return EntityBatch()

    # AllItems.aspx file preview: fetch the specific file via REST
    if sharing_url and _is_file_preview_url(sharing_url):
        result = _fetch_file_preview(sharing_url, resource_id)
        if result is not None:
            return result
        logger.info("File preview fetch failed for %s", resource_id)
        return EntityBatch()

    # Strategy 1: direct download via sharing link or server-relative URL
    if sharing_url:
        result = _try_direct_download(sharing_url, resource_id)
        if result is not None:
            return result
        # Server-relative URLs (e.g. from folder listings) won't work with Graph API
        if not _is_sharing_link(sharing_url):
            logger.info("Direct download failed for server-relative URL %s — no fallback", resource_id)
            return EntityBatch()
        logger.info("Direct download failed for %s — falling back to Graph API", resource_id)

    # Strategy 2: Microsoft Graph API (requires SPO licence on authenticated account)
    return _fetch_via_graph(resource_id, sharing_url)


def _list_folder(folder_url: str, resource_id: str) -> EntityBatch | None:
    """List files in a SharePoint folder via REST API and return an EntityBatch of stubs."""
    import httpx
    from urllib.parse import parse_qs, unquote, urlparse
    from agentgraph.auth.sharepoint import get_cookies_for_url

    cookies = get_cookies_for_url(folder_url)
    if not cookies:
        logger.debug("No cookies for %s — cannot list folder", folder_url)
        return None

    parsed = urlparse(folder_url)
    domain = parsed.netloc

    # Extract server-relative folder path from AllItems.aspx?id= parameter.
    # For sharing links (/:f:/), follow the redirect to get the AllItems.aspx URL.
    if "AllItems.aspx" in folder_url:
        params = parse_qs(parsed.query)
        folder_path = unquote(params.get("id", [""])[0])
    elif "/:f:/" in folder_url:
        # Follow the sharing link redirect — SharePoint returns an AllItems.aspx URL
        with httpx.Client(timeout=30, follow_redirects=True, cookies=cookies) as client:
            resp = client.get(folder_url)
        if not resp.is_success:
            logger.warning("Failed to resolve folder sharing link %s: %s", folder_url, resp.status_code)
            return None
        final_url = str(resp.url)
        domain = urlparse(final_url).netloc
        if "AllItems.aspx" not in final_url:
            logger.debug("Sharing link did not redirect to AllItems.aspx: %s", final_url)
            return None
        params = parse_qs(urlparse(final_url).query)
        folder_path = unquote(params.get("id", [""])[0])
    else:
        logger.debug("Unsupported folder URL format: %s", folder_url)
        return None

    if not folder_path:
        return None

    # Determine site path: /sites/{site} prefix of the folder path
    import re as _re
    site_match = _re.search(r"^(/sites/[^/]+)", folder_path)
    site_path = site_match.group(1) if site_match else ""

    from urllib.parse import quote
    api_url = (
        f"https://{domain}{site_path}/_api/web/"
        f"GetFolderByServerRelativeUrl('{quote(folder_path)}')/Files"
    )

    with httpx.Client(timeout=30, follow_redirects=True, cookies=cookies) as client:
        resp = client.get(api_url, headers={"Accept": "application/json;odata=verbose"})

    if not resp.is_success:
        logger.warning("SharePoint folder REST API returned %s for %s", resp.status_code, api_url)
        return None

    data = resp.json()
    files: list[dict[str, Any]] = data.get("d", {}).get("results", [])

    if not files:
        logger.info("Folder is empty or REST API returned no files: %s", folder_url)

    stubs: list[EntityRecord] = []
    edges: list[EdgeRecord] = []

    for f in files:
        name: str = f.get("Name", "")
        server_rel: str = f.get("ServerRelativeUrl", "")
        if not server_rel:
            continue
        file_url = f"https://{domain}{server_rel}"
        encoded = base64.urlsafe_b64encode(file_url.encode()).rstrip(b"=").decode()
        file_resource_id = f"u!{encoded}"

        stubs.append(EntityRecord(
            entity_type="Document",
            platform="sharepoint",
            platform_entity_id=file_resource_id,
            title=name,
            is_stub=True,
        ))
        edges.append(EdgeRecord(
            edge_type="contains",
            source_platform_entity_id=resource_id,
            target_platform_entity_id=file_resource_id,
            platform="sharepoint",
        ))

    folder_entity = EntityRecord(
        entity_type="Folder",
        platform="sharepoint",
        platform_entity_id=resource_id,
        title=folder_path.rstrip("/").rsplit("/", 1)[-1],
        metadata={"web_url": folder_url},
    )

    logger.info("Listed %d files in SharePoint folder %s", len(stubs), folder_path)
    return EntityBatch(entities=[folder_entity, *stubs], edges=edges)


def _fetch_file_preview(preview_url: str, resource_id: str) -> EntityBatch | None:
    """Fetch a file referenced in an AllItems.aspx?id=<path> preview URL.

    Uses GetFileByServerRelativeUrl to read metadata. For text/office files
    also downloads content; for binary files (images, etc.) stores title only.
    """
    import httpx
    import os
    from urllib.parse import parse_qs, unquote, urlparse
    from agentgraph.auth.sharepoint import get_cookies_for_url

    cookies = get_cookies_for_url(preview_url)
    if not cookies:
        logger.debug("No cookies for %s — cannot fetch file preview", preview_url)
        return None

    parsed = urlparse(preview_url)
    domain = parsed.netloc
    params = parse_qs(parsed.query)
    file_path = unquote(params.get("id", [""])[0])
    if not file_path:
        return None

    import re as _re
    site_match = _re.search(r"^(/sites/[^/]+|/personal/[^/]+)", file_path)
    site_path = site_match.group(1) if site_match else ""

    from urllib.parse import quote
    meta_url = (
        f"https://{domain}{site_path}/_api/web/"
        f"GetFileByServerRelativeUrl('{quote(file_path)}')"
        f"?$select=Name,ServerRelativeUrl,TimeCreated,TimeLastModified,Length,Author/Title,Author/EMail"
        f"&$expand=Author"
    )

    with httpx.Client(timeout=30, follow_redirects=True, cookies=cookies) as client:
        resp = client.get(meta_url, headers={"Accept": "application/json;odata=verbose"})

    if not resp.is_success:
        logger.warning(
            "SharePoint file REST API returned %s for %s", resp.status_code, meta_url
        )
        return None

    data = resp.json().get("d", {})
    title: str = data.get("Name", os.path.basename(file_path))
    web_url = f"https://{domain}{data.get('ServerRelativeUrl', file_path)}"
    created_at = _parse_dt(data.get("TimeCreated"))
    updated_at = _parse_dt(data.get("TimeLastModified"))

    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []
    author = data.get("Author") or {}
    author_email: str = author.get("EMail", "")
    author_name: str = author.get("Title", "")
    if author_email:
        persons.append(PersonRecord(
            platform="sharepoint",
            platform_user_id=author_email,
            canonical_email=author_email,
            display_name=author_name or None,
        ))
        edges.append(EdgeRecord(
            edge_type="authored",
            source_platform_user_id=author_email,
            target_platform_entity_id=resource_id,
            platform="sharepoint",
        ))

    # Try to download content for known text/office formats
    content: str | None = None
    _, ext = os.path.splitext(title.lower())
    if ext in (".docx",):
        download_url = (
            f"https://{domain}{site_path}/_api/web/"
            f"GetFileByServerRelativeUrl('{quote(file_path)}')/$value"
        )
        with httpx.Client(timeout=30, follow_redirects=True, cookies=cookies) as client:
            dl = client.get(download_url)
        if dl.is_success and dl.content.startswith(b"PK"):
            content = _extract_docx(dl.content)

    entity = EntityRecord(
        entity_type="Document",
        platform="sharepoint",
        platform_entity_id=resource_id,
        title=title,
        content=content,
        created_at=created_at,
        updated_at=updated_at,
        metadata={"web_url": web_url},
    )
    logger.info("Fetched SharePoint file preview %s (%s)", resource_id, title)
    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch


def _try_direct_download(sharing_url: str, resource_id: str) -> EntityBatch | None:
    """Attempt a direct download using the sharing link.

    Tries cookie auth first (FedAuth+rtFa from agentgraph auth sharepoint),
    then falls back to anonymous. Returns None if the document is not accessible.
    """
    import httpx
    from agentgraph.auth.sharepoint import get_cookies_for_url

    # SharePoint sharing links support ?download=1 to force a file download
    sep = "&" if "?" in sharing_url else "?"
    download_url = f"{sharing_url}{sep}download=1"

    cookies = get_cookies_for_url(sharing_url)
    if cookies:
        logger.debug("Using stored SharePoint cookies for %s", sharing_url)
    else:
        logger.debug("No stored cookies for %s — trying anonymous", sharing_url)

    try:
        with httpx.Client(timeout=30, follow_redirects=True, cookies=cookies) as client:
            resp = client.get(download_url)
    except Exception as exc:
        logger.warning("Direct download request failed: %s", exc)
        return None

    if not resp.is_success:
        logger.debug("Direct download returned %s", resp.status_code)
        return None

    # If we got HTML back, the cookies didn't work (login page)
    content_type = resp.headers.get("content-type", "")
    if "html" in content_type:
        if cookies:
            logger.warning(
                "SharePoint returned HTML despite cookies for %s — cookies may have expired. "
                "Run: agentgraph auth sharepoint",
                sharing_url,
            )
        else:
            logger.debug("Anonymous download returned HTML (login required): %s", sharing_url)
        return None

    title = _filename_from_headers(resp.headers) or _filename_from_url(sharing_url)

    if resp.content.startswith(b"PK"):  # ZIP/OOXML magic bytes
        content = _extract_docx(resp.content)
    elif b"%PDF" in resp.content[:8]:
        content = None  # PDF — no parser available yet
        logger.info("Downloaded PDF %s — stored without content", title)
    else:
        logger.debug("Direct download returned unrecognised content-type: %s", content_type)
        return None

    entity = EntityRecord(
        entity_type="Document",
        platform="sharepoint",
        platform_entity_id=resource_id,
        title=title,
        content=content,
        metadata={"web_url": sharing_url},
    )
    batch = EntityBatch(entities=[entity])
    batch.add_stubs_from(entity)
    logger.info("Direct download succeeded for %s (%s)", resource_id, title)
    return batch


def _fetch_via_graph(resource_id: str, sharing_url: str | None) -> EntityBatch:
    """Fetch document metadata and content via Microsoft Graph API."""
    import httpx
    from agentgraph.auth.microsoft_provider import get_provider

    token = get_provider().get_access_token()
    headers = {"Authorization": f"Bearer {token}"}

    if resource_id.startswith("u!"):
        shares_id = resource_id
    else:
        encoded = base64.urlsafe_b64encode(resource_id.encode()).rstrip(b"=").decode()
        shares_id = f"u!{encoded}"

    with httpx.Client(timeout=30) as client:
        meta_resp = client.get(
            f"{_GRAPH_BASE}/shares/{shares_id}/driveItem",
            headers=headers,
            params={"$select": "id,name,file,createdBy,lastModifiedBy,createdDateTime,lastModifiedDateTime,webUrl"},
        )
        if not meta_resp.is_success:
            try:
                err_body = meta_resp.json()
            except Exception:
                err_body = meta_resp.text
            logger.error(
                "SharePoint Graph API error %s for %s: %s",
                meta_resp.status_code,
                shares_id,
                err_body,
            )
            if meta_resp.status_code == 404:
                raise ValueError(f"SharePoint item not found or not accessible: {resource_id}")
            meta_resp.raise_for_status()
        item: dict[str, Any] = meta_resp.json()

        title: str = item.get("name", "")
        web_url: str = item.get("webUrl", sharing_url or "")
        created_at = _parse_dt(item.get("createdDateTime"))
        updated_at = _parse_dt(item.get("lastModifiedDateTime"))
        mime_type: str = (item.get("file") or {}).get("mimeType", "")

        content: str | None = None
        if mime_type == _DOCX_MIME:
            content_resp = client.get(
                f"{_GRAPH_BASE}/shares/{shares_id}/driveItem/content",
                headers=headers,
                follow_redirects=True,
            )
            if content_resp.is_success:
                content = _extract_docx(content_resp.content)

    persons: list[PersonRecord] = []
    edges: list[EdgeRecord] = []

    author_email = _extract_email(item.get("createdBy"))
    author_name = _extract_name(item.get("createdBy"))
    if author_email:
        persons.append(PersonRecord(
            platform="sharepoint",
            platform_user_id=author_email,
            canonical_email=author_email,
            display_name=author_name or None,
        ))
        edges.append(EdgeRecord(
            edge_type="authored",
            source_platform_user_id=author_email,
            target_platform_entity_id=resource_id,
            platform="sharepoint",
        ))

    editor_email = _extract_email(item.get("lastModifiedBy"))
    editor_name = _extract_name(item.get("lastModifiedBy"))
    if editor_email and editor_email != author_email:
        persons.append(PersonRecord(
            platform="sharepoint",
            platform_user_id=editor_email,
            canonical_email=editor_email,
            display_name=editor_name or None,
        ))
        edges.append(EdgeRecord(
            edge_type="collaborated",
            source_platform_user_id=editor_email,
            target_platform_entity_id=resource_id,
            platform="sharepoint",
        ))

    entity = EntityRecord(
        entity_type="Document",
        platform="sharepoint",
        platform_entity_id=resource_id,
        title=title,
        content=content,
        created_at=created_at,
        updated_at=updated_at,
        metadata={"web_url": web_url, "mime_type": mime_type},
    )

    batch = EntityBatch(entities=[entity], persons=persons, edges=edges)
    batch.add_stubs_from(entity)
    return batch


def _filename_from_headers(headers: Any) -> str | None:
    cd = headers.get("content-disposition", "")
    for part in cd.split(";"):
        part = part.strip()
        if part.startswith("filename*="):
            # RFC 5987 encoded, e.g. filename*=UTF-8''My%20Doc.docx
            val = part[10:].split("''", 1)[-1]
            from urllib.parse import unquote
            return unquote(val)
        if part.startswith('filename="') and part.endswith('"'):
            return part[10:-1]
        if part.startswith("filename="):
            return part[9:]
    return None


def _filename_from_url(url: str) -> str | None:
    from urllib.parse import urlparse
    path = urlparse(url).path
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return name or None


def _extract_docx(data: bytes) -> str | None:
    try:
        import docx  # type: ignore[import-untyped]

        doc = docx.Document(io.BytesIO(data))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs) or None
    except Exception as exc:
        logger.warning("Failed to extract DOCX content: %s", exc)
        return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_email(by: dict[str, Any] | None) -> str | None:
    if not by:
        return None
    user = by.get("user") or {}
    return user.get("email") or user.get("userPrincipalName") or None


def _extract_name(by: dict[str, Any] | None) -> str | None:
    if not by:
        return None
    user = by.get("user") or {}
    return user.get("displayName") or None
