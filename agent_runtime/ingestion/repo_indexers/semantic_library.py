"""Semantic library artifact helpers for optional repo indexing.

The semantic library is intentionally conservative. It records what the repo
indexing subsystem knows without claiming that a real CodeGraph index exists
unless an approved adapter run reports it. This keeps P1-D useful in dry-run
mode while preserving the no-clone/no-unapproved-indexing policy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def display_repo_path(repo_path: Path) -> str:
    """Return a stable, non-sensitive repo path display value."""

    if repo_path.exists():
        return repo_path.resolve().name
    return str(repo_path)


def empty_symbol_index() -> list[dict[str, Any]]:
    """Return the empty symbol list used before real indexing is approved."""

    return []


def normalize_queries(queries: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Normalize query entries so JSON artifact structure stays stable."""

    normalized: list[dict[str, Any]] = []
    for query in queries or []:
        normalized.append(
            {
                "query": query.get("query"),
                "tool": query.get("tool", "search"),
                "result_count": int(query.get("result_count") or 0),
                "warnings": list(query.get("warnings") or []),
            }
        )
    return normalized


def semantic_library(
    repo_path: Path,
    *,
    indexer: str,
    index_status: str,
    queries: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a serializable semantic library artifact.

    Real symbol extraction is intentionally absent from this helper. The
    CodeGraph adapter owns the boundary to external CLI execution, while this
    function only shapes evidence artifacts consumed by validation gates.
    """

    return {
        "schema_version": SCHEMA_VERSION,
        "repo_path": display_repo_path(repo_path),
        "indexer": indexer,
        "index_status": index_status,
        "symbols": empty_symbol_index(),
        "queries": normalize_queries(queries),
        "warnings": list(warnings or []),
        "limitations": [
            "real indexing requires local CLI availability",
            "real indexing requires explicit approval",
            "dry-run artifacts do not include extracted symbols",
        ],
    }
