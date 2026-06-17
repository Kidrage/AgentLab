"""R3: Local Search and Project Knowledge Index.

Deterministic, stdlib-only text index for local repository knowledge.
Never fetches from external sources. Never indexes secrets.
"""

from __future__ import annotations

from .document import Document, SourceCategory
from .indexer import build_index, index_directory
from .query import QueryResult, query_index, score_bm25
from .storage import load_index, save_index, index_status
from .evidence import EvidenceSnippet

__all__ = [
    "Document",
    "SourceCategory",
    "EvidenceSnippet",
    "QueryResult",
    "build_index",
    "index_directory",
    "query_index",
    "score_bm25",
    "load_index",
    "save_index",
    "index_status",
]
