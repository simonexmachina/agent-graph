"""HTTP retrieval shared by the web and RSS connectors."""

# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import logging
from collections.abc import AsyncIterable, Mapping
from dataclasses import dataclass

import httpx
from curl_cffi.requests import AsyncSession

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_DEFAULT_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class HttpFetchResult:
    """A fully-read HTTP response independent of the underlying client."""

    url: str
    status_code: int
    headers: dict[str, str]
    content: bytes


async def fetch_http_resource(
    url: str,
    *,
    headers: Mapping[str, str],
    max_bytes: int,
    too_large_message: str,
    timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
    max_redirects: int = _DEFAULT_MAX_REDIRECTS,
    client: httpx.AsyncClient | None = None,
) -> HttpFetchResult:
    """Fetch an HTTP resource, retrying Cloudflare challenges with browser fingerprints."""
    primary, challenged = await _fetch_with_httpx(
        url,
        headers=headers,
        max_bytes=max_bytes,
        too_large_message=too_large_message,
        timeout=timeout,
        max_redirects=max_redirects,
        client=client,
    )
    if not challenged:
        return primary

    logger.debug("Retrying Cloudflare challenge with browser impersonation for %s", url)
    return await _fetch_with_impersonation(
        url,
        headers=headers,
        max_bytes=max_bytes,
        too_large_message=too_large_message,
        timeout=timeout,
        max_redirects=max_redirects,
    )


async def _fetch_with_httpx(
    url: str,
    *,
    headers: Mapping[str, str],
    max_bytes: int,
    too_large_message: str,
    timeout: httpx.Timeout,
    max_redirects: int,
    client: httpx.AsyncClient | None,
) -> tuple[HttpFetchResult, bool]:
    if client is None:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=max_redirects,
            timeout=timeout,
        ) as owned_client:
            return await _fetch_with_httpx(
                url,
                headers=headers,
                max_bytes=max_bytes,
                too_large_message=too_large_message,
                timeout=timeout,
                max_redirects=max_redirects,
                client=owned_client,
            )

    async with client.stream("GET", url, headers=dict(headers)) as response:
        if _is_cloudflare_challenge(response):
            return (
                HttpFetchResult(
                    url=str(response.url),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=b"",
                ),
                True,
            )
        if response.status_code != 304:
            response.raise_for_status()
        content = await _read_limited_body(
            response.aiter_bytes(),
            max_bytes=max_bytes,
            too_large_message=too_large_message,
        )
        return (
            HttpFetchResult(
                url=str(response.url),
                status_code=response.status_code,
                headers=dict(response.headers),
                content=content,
            ),
            False,
        )


async def _fetch_with_impersonation(
    url: str,
    *,
    headers: Mapping[str, str],
    max_bytes: int,
    too_large_message: str,
    timeout: httpx.Timeout,
    max_redirects: int,
) -> HttpFetchResult:
    async with AsyncSession() as session, session.stream(
        "GET",
        url,
        headers=_impersonation_headers(headers),
        timeout=_curl_timeout(timeout),
        allow_redirects=True,
        max_redirects=max_redirects,
        impersonate="chrome",
    ) as response:
        response.raise_for_status()
        content = await _read_limited_body(
            response.aiter_content(),
            max_bytes=max_bytes,
            too_large_message=too_large_message,
        )
        return HttpFetchResult(
            url=str(response.url),
            status_code=response.status_code,
            headers=dict(response.headers),
            content=content,
        )


async def _read_limited_body(
    chunks: AsyncIterable[bytes],
    *,
    max_bytes: int,
    too_large_message: str,
) -> bytes:
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ValueError(too_large_message)
    return bytes(body)


def _is_cloudflare_challenge(response: httpx.Response) -> bool:
    return response.status_code == 403 and response.headers.get("cf-mitigated") == "challenge"


def _impersonation_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Keep request semantics while allowing curl_cffi to set a browser user agent."""
    return {key: value for key, value in headers.items() if key.lower() != "user-agent"}


def _curl_timeout(timeout: httpx.Timeout) -> float | tuple[float, float] | None:
    connect_timeout = timeout.connect
    read_timeout = timeout.read
    if connect_timeout is None and read_timeout is None:
        return None
    if connect_timeout is None:
        return read_timeout
    if read_timeout is None:
        return connect_timeout
    return (connect_timeout, read_timeout)
