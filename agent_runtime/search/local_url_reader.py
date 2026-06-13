"""Small safe URL extraction fallback for AgentLab search."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.request
from urllib.parse import urlparse

from .provider import SearchProvider, UrlExtractResponse, unknown_usage


def _is_blocked_host(hostname: str | None, *, block_localhost: bool = True, block_private: bool = True) -> bool:
    if not hostname:
        return True
    host = hostname.lower()
    if block_localhost and host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
        except Exception:
            return False
    return any(addr.is_loopback or (block_private and (addr.is_private or addr.is_link_local)) for addr in addresses)


class LocalUrlReader(SearchProvider):
    provider_name = "local_url_reader"

    def __init__(
        self,
        *,
        http_get=None,
        block_localhost: bool = True,
        block_private: bool = True,
        max_bytes: int = 200_000,
    ):
        self.http_get = http_get or self._urllib_get
        self.block_localhost = block_localhost
        self.block_private = block_private
        self.max_bytes = max_bytes

    def search_web(self, query: str, *, max_results: int = 5, vertical: str | None = None):
        from .provider import SearchResponse

        return SearchResponse(
            provider=self.provider_name,
            query=query,
            vertical=vertical,
            warnings=["local_url_reader does not perform web search"],
            usage=unknown_usage(0),
            status="skipped",
            auth_mode="disabled",
        )

    def batch_search(self, queries: list[str], *, max_results: int = 5):
        from .provider import BatchSearchResponse

        responses = [self.search_web(q, max_results=max_results) for q in queries]
        return BatchSearchResponse(
            provider=self.provider_name,
            responses=responses,
            warnings=["local_url_reader does not perform batch search"],
            usage=unknown_usage(0),
            status="skipped",
            auth_mode="disabled",
        )

    def extract_url(self, url: str, *, max_chars: int = 12000) -> UrlExtractResponse:
        parsed = urlparse(url)
        warnings: list[str] = []
        if parsed.scheme not in {"http", "https"}:
            return UrlExtractResponse(
                provider=self.provider_name,
                url=url,
                source=url,
                warnings=[f"blocked unsupported URL scheme: {parsed.scheme or 'missing'}"],
                usage=unknown_usage(0),
                status="rejected",
                auth_mode="disabled",
            )
        if _is_blocked_host(
            parsed.hostname,
            block_localhost=self.block_localhost,
            block_private=self.block_private,
        ):
            return UrlExtractResponse(
                provider=self.provider_name,
                url=url,
                source=url,
                warnings=["blocked localhost/private/link-local URL"],
                usage=unknown_usage(0),
                status="rejected",
                auth_mode="disabled",
            )
        try:
            body = self.http_get(url, self.max_bytes)
        except Exception as exc:
            return UrlExtractResponse(
                provider=self.provider_name,
                url=url,
                source=url,
                warnings=[f"fetch failed: {exc}"],
                usage=unknown_usage(1),
                status="error",
                auth_mode="disabled",
            )
        text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else str(body)
        if len(text) > max_chars:
            text = text[:max_chars]
            warnings.append("text truncated to max_chars")
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"\s+", " ", plain).strip()
        return UrlExtractResponse(
            provider=self.provider_name,
            url=url,
            title=title,
            text=plain[:max_chars],
            source=url,
            warnings=warnings,
            usage=unknown_usage(1),
            status="ok",
            auth_mode="disabled",
        )

    def _urllib_get(self, url: str, max_bytes: int) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "AgentLab-local-url-reader/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:  # nosec - guarded by policy, mocked in tests
            return resp.read(max_bytes + 1)[:max_bytes]
