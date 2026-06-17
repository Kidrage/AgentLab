from __future__ import annotations

"""Fetcher interface and mock implementation for AgentLab web intelligence.

The real fetcher (HTTP via stdlib ``urllib``) is intentionally *not*
implemented here — only the abstract interface and a deterministic
``MockFetcher`` that needs no network.  This keeps the module fully
testable offline.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FetchResult:
    """Immutable record returned by every fetch operation."""

    url: str
    status_code: int
    content_type: str
    body: str
    content_hash: str
    fetched_at: str
    error: str | None = None

    @staticmethod
    def make_hash(body: str) -> str:
        """Return the SHA-256 hex digest of *body*."""
        return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Abstract fetcher
# ---------------------------------------------------------------------------

class WebFetcher(ABC):
    """Abstract base class for web content fetchers.

    Concrete implementations may use ``urllib.request``, ``httpx``,
    or any other transport.  The interface is intentionally minimal
    so that mocking is trivial.
    """

    @abstractmethod
    def fetch(self, url: str) -> FetchResult:
        """Fetch the resource at *url* and return a ``FetchResult``."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Mock fetcher
# ---------------------------------------------------------------------------

class MockFetcher(WebFetcher):
    """Deterministic fetcher backed by an in-memory URL -> response map.

    Use this in tests and in the ``mock_first`` policy mode to exercise
    the full pipeline without any network I/O.

    Example
    -------
    >>> fetcher = MockFetcher()
    >>> fetcher.register(
    ...     "https://example.com/page",
    ...     status_code=200,
    ...     content_type="text/html",
    ...     body="<html><body>Hello</body></html>",
    ... )
    >>> result = fetcher.fetch("https://example.com/page")
    >>> result.status_code
    200
    """

    def __init__(self) -> None:
        self._registry: dict[str, FetchResult] = {}

    # -- registration -------------------------------------------------------

    def register(
        self,
        url: str,
        *,
        status_code: int = 200,
        content_type: str = "text/html",
        body: str = "",
        error: str | None = None,
    ) -> None:
        """Add a canned response for *url*."""
        now = datetime.now(timezone.utc).isoformat()
        self._registry[url] = FetchResult(
            url=url,
            status_code=status_code,
            content_type=content_type,
            body=body,
            content_hash=FetchResult.make_hash(body),
            fetched_at=now,
            error=error,
        )

    def register_batch(self, mappings: dict[str, str]) -> None:
        """Convenience: register many URL -> body pairs at once.

        All entries default to 200 / text/html.
        """
        for url, body in mappings.items():
            self.register(url, body=body)

    # -- fetch --------------------------------------------------------------

    def fetch(self, url: str) -> FetchResult:
        """Return the pre-registered response for *url*, or a 404 stub."""
        if url in self._registry:
            return self._registry[url]

        now = datetime.now(timezone.utc).isoformat()
        body = ""
        return FetchResult(
            url=url,
            status_code=404,
            content_type="text/plain",
            body=body,
            content_hash=FetchResult.make_hash(body),
            fetched_at=now,
            error="Mock: URL not registered",
        )

    # -- introspection ------------------------------------------------------

    def registered_urls(self) -> list[str]:
        """Return a sorted list of all registered URLs."""
        return sorted(self._registry)

    def clear(self) -> None:
        """Remove all registered responses."""
        self._registry.clear()
