"""Evidence snippet for search results."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EvidenceSnippet:
    path: str
    line_start: int | None
    line_end: int | None
    snippet: str
    score: float
    source_category: str
    content_hash: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "snippet": self.snippet,
            "score": self.score,
            "source_category": self.source_category,
            "content_hash": self.content_hash,
        }
