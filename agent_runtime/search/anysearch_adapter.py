"""Optional AnySearch adapter.

The adapter is disabled by default and exposes a mockable HTTP wrapper. Tests
should inject ``http_post``/``url_reader`` or use ``mock=True``.
"""

from __future__ import annotations

import os
from typing import Any

from .local_url_reader import LocalUrlReader
from .provider import (
    BatchSearchResponse,
    SearchProvider,
    SearchResponse,
    SearchResult,
    UrlExtractResponse,
    unknown_usage,
)


class AnySearchAdapter(SearchProvider):
    provider_name = "anysearch"

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        http_post=None,
        url_reader: SearchProvider | None = None,
        mock: bool = False,
    ):
        self.config = config or {}
        self.http_post = http_post
        self.url_reader = url_reader or LocalUrlReader()
        self.mock = mock
        self.api_key_env = self.config.get("api_key_env", "ANYSEARCH_API_KEY")
        self.api_key = os.getenv(self.api_key_env)

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    @property
    def auth_mode(self) -> str:
        if not self.enabled and not self.mock:
            return "disabled"
        if self.mock:
            return "mock"
        if self.api_key:
            return "api_key"
        if self.config.get("allow_anonymous", True):
            return "anonymous"
        return "disabled"

    def search_web(self, query: str, *, max_results: int = 5, vertical: str | None = None) -> SearchResponse:
        if self.mock:
            result = SearchResult(
                title=f"Mock result for {query}",
                url="https://example.com/mock-search",
                snippet=f"Mock AnySearch response for {query}",
                source="anysearch.mock",
                rank=1,
                confidence=0.9,
            )
            return SearchResponse(self.provider_name, query, vertical, [result], [], unknown_usage(1), "ok", "mock")
        if not self.enabled:
            return SearchResponse(
                self.provider_name,
                query,
                vertical,
                [],
                ["AnySearch provider disabled; planned/skipped without external call"],
                unknown_usage(0),
                "skipped",
                "disabled",
            )
        if self.auth_mode == "disabled":
            return SearchResponse(
                self.provider_name,
                query,
                vertical,
                [],
                [f"{self.api_key_env} missing and anonymous mode disabled"],
                unknown_usage(0),
                "setup_required",
                "disabled",
            )
        if self.http_post is None:
            return SearchResponse(
                self.provider_name,
                query,
                vertical,
                [],
                ["AnySearch HTTP wrapper not configured; no external call performed"],
                unknown_usage(0),
                "setup_required",
                self.auth_mode,
            )
        payload = {"query": query, "max_results": max_results, "vertical": vertical}
        raw = self.http_post("/search", payload, self._headers())
        return self._parse_search_response(query, vertical, raw)

    def batch_search(self, queries: list[str], *, max_results: int = 5) -> BatchSearchResponse:
        max_batch = int(self.config.get("max_batch_queries", 5) or 5)
        approval_over = int((self.config.get("safety") or {}).get("require_approval_for_batch_over", max_batch) or max_batch)
        if len(queries) > approval_over:
            return BatchSearchResponse(
                self.provider_name,
                [],
                [f"batch size {len(queries)} exceeds approval threshold {approval_over}"],
                unknown_usage(0),
                "pending_approval",
                self.auth_mode,
            )
        responses = [self.search_web(q, max_results=max_results) for q in queries[:max_batch]]
        status = "ok" if all(r.status == "ok" for r in responses) else "skipped"
        return BatchSearchResponse(
            self.provider_name,
            responses,
            [],
            unknown_usage(len(responses)),
            status,
            self.auth_mode,
        )

    def extract_url(self, url: str, *, max_chars: int = 12000) -> UrlExtractResponse:
        if self.mock:
            return UrlExtractResponse(
                provider=self.provider_name,
                url=url,
                title="Mock URL extraction",
                text="Mock extracted text",
                source=url,
                usage=unknown_usage(1),
                status="ok",
                auth_mode="mock",
            )
        if not self.enabled:
            response = self.url_reader.extract_url(url, max_chars=max_chars)
            response.warnings.insert(0, "AnySearch provider disabled; used local_url_reader fallback")
            return response
        if self.http_post is None:
            return self.url_reader.extract_url(url, max_chars=max_chars)
        raw = self.http_post(
            "/extract",
            {"url": url, "max_chars": max_chars},
            self._headers(),
        )
        return UrlExtractResponse(
            provider=self.provider_name,
            url=url,
            title=raw.get("title"),
            text=str(raw.get("text") or "")[:max_chars],
            source=url,
            warnings=list(raw.get("warnings") or []),
            usage=unknown_usage(1),
            status="ok",
            auth_mode=self.auth_mode,
        )

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": "Bearer REDACTED"}
        return {}

    def _parse_search_response(self, query: str, vertical: str | None, raw: dict[str, Any]) -> SearchResponse:
        results = []
        for idx, item in enumerate(raw.get("results") or [], start=1):
            url = str(item.get("url") or "")
            results.append(SearchResult(
                title=str(item.get("title") or url),
                url=url,
                snippet=str(item.get("snippet") or ""),
                source=str(item.get("source") or "anysearch"),
                rank=int(item.get("rank") or idx),
                confidence=item.get("confidence"),
            ))
        return SearchResponse(
            self.provider_name,
            query,
            vertical,
            results,
            list(raw.get("warnings") or []),
            unknown_usage(1),
            "ok",
            self.auth_mode,
        )
