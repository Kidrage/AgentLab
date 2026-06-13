"""Provider-neutral search data contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

try:
    from state_store import utc_now
except ImportError:  # pragma: no cover
    from agent_runtime.state_store import utc_now


def unknown_usage(request_count: int = 1) -> dict[str, Any]:
    return {
        "api_provider_cost_visible": False,
        "token_visibility": "unknown",
        "request_count": request_count,
    }


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str
    retrieved_at: str = field(default_factory=utc_now)
    rank: int = 1
    confidence: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResponse:
    provider: str
    query: str
    vertical: str | None = None
    results: list[SearchResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=unknown_usage)
    status: str = "ok"
    auth_mode: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["results"] = [
            r.as_dict() if hasattr(r, "as_dict") else dict(r)
            for r in self.results
        ]
        return data


@dataclass
class BatchSearchResponse:
    provider: str
    responses: list[SearchResponse] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=lambda: unknown_usage(0))
    status: str = "ok"
    auth_mode: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["responses"] = [
            r.as_dict() if hasattr(r, "as_dict") else dict(r)
            for r in self.responses
        ]
        return data


@dataclass
class UrlExtractResponse:
    provider: str
    url: str
    title: str | None = None
    text: str = ""
    source: str = ""
    retrieved_at: str = field(default_factory=utc_now)
    warnings: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=unknown_usage)
    status: str = "ok"
    auth_mode: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SearchProvider:
    """Search provider interface. Implementations must return serializable dataclasses."""

    provider_name = "abstract"

    def search_web(
        self,
        query: str,
        *,
        max_results: int = 5,
        vertical: str | None = None,
    ) -> SearchResponse:
        raise NotImplementedError

    def batch_search(
        self,
        queries: list[str],
        *,
        max_results: int = 5,
    ) -> BatchSearchResponse:
        raise NotImplementedError

    def extract_url(self, url: str, *, max_chars: int = 12000) -> UrlExtractResponse:
        raise NotImplementedError
