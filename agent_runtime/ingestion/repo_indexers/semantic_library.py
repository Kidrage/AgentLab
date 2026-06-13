"""Semantic library artifact helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def semantic_library(
    repo_path: Path,
    *,
    indexer: str,
    index_status: str,
    queries: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "repo_path": repo_path.resolve().name if repo_path.exists() else str(repo_path),
        "indexer": indexer,
        "index_status": index_status,
        "symbols": [],
        "queries": list(queries or []),
        "warnings": list(warnings or []),
    }
