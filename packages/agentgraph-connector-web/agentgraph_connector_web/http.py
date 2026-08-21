"""HTTP retrieval shared by the web and RSS connectors."""

# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false, reportUnknownVariableType=false

from __future__ import annotations

import codecs
import logging
import re
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
    compact_html: bool = False,
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
        compact_html=compact_html,
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
        compact_html=compact_html,
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
    compact_html: bool,
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
                compact_html=compact_html,
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
            compact_html=compact_html and _is_html_content_type(response.headers.get("content-type")),
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
    compact_html: bool,
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
            compact_html=compact_html and _is_html_content_type(response.headers.get("content-type")),
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
    compact_html: bool = False,
) -> bytes:
    body = bytearray()
    html_filter = _HTMLNoiseFilter() if compact_html else None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace") if html_filter else None
    async for chunk in chunks:
        if html_filter is not None and decoder is not None:
            body.extend(html_filter.feed(decoder.decode(chunk)))
        else:
            body.extend(chunk)
        if len(body) > max_bytes:
            raise ValueError(too_large_message)
    if html_filter is not None and decoder is not None:
        body.extend(html_filter.feed(decoder.decode(b"", final=True)))
        body.extend(html_filter.finish())
        if len(body) > max_bytes:
            raise ValueError(too_large_message)
    return bytes(body)


class _HTMLNoiseFilter:
    """Remove non-content HTML blocks while retaining the surrounding source."""

    _BLOCK_TAG = re.compile(r"<\s*(style|script|noscript)\b", re.IGNORECASE)
    _COMMENT = "<!--"

    def __init__(self) -> None:
        self._buffer = ""
        self._suppressed_tag: str | None = None

    def feed(self, text: str) -> bytes:
        self._buffer += text
        return self._process().encode("utf-8")

    def finish(self) -> bytes:
        if self._suppressed_tag is not None:
            return b""
        return self._buffer.encode("utf-8")

    def _process(self) -> str:
        output: list[str] = []
        while True:
            if self._suppressed_tag is not None:
                close = re.search(
                    rf"</\s*{self._suppressed_tag}\b[^>]*>",
                    self._buffer,
                    re.IGNORECASE,
                )
                if close is None:
                    self._buffer = self._buffer[-32:]
                    break
                self._buffer = self._buffer[close.end() :]
                self._suppressed_tag = None
                continue

            comment_start = self._buffer.lower().find(self._COMMENT)
            block_start = self._BLOCK_TAG.search(self._buffer)
            if comment_start < 0 and block_start is None:
                last_lt = self._buffer.rfind("<")
                if last_lt >= 0 and ">" not in self._buffer[last_lt:]:
                    output.append(self._buffer[:last_lt])
                    self._buffer = self._buffer[last_lt:]
                else:
                    output.append(self._buffer)
                    self._buffer = ""
                break

            next_start = len(self._buffer)
            if comment_start >= 0:
                next_start = comment_start
            if block_start is not None:
                next_start = min(next_start, block_start.start())
            output.append(self._buffer[:next_start])
            self._buffer = self._buffer[next_start:]

            if self._buffer.startswith(self._COMMENT):
                comment_end = self._buffer.find("-->", len(self._COMMENT))
                if comment_end < 0:
                    break
                self._buffer = self._buffer[comment_end + 3 :]
                continue

            tag = self._BLOCK_TAG.match(self._buffer)
            if tag is None:
                output.append(self._buffer[:1])
                self._buffer = self._buffer[1:]
                continue
            tag_end = self._buffer.find(">", tag.end())
            if tag_end < 0:
                break
            self._suppressed_tag = tag.group(1).lower()
            self._buffer = self._buffer[tag_end + 1 :]
        return "".join(output)


def _is_cloudflare_challenge(response: httpx.Response) -> bool:
    return response.status_code == 403 and response.headers.get("cf-mitigated") == "challenge"


def _is_html_content_type(content_type: str | None) -> bool:
    return (content_type or "").split(";", 1)[0].strip().lower() in {
        "text/html",
        "application/xhtml+xml",
    }


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
