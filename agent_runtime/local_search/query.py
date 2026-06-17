"""BM25-based query engine for the local search index.

Provides tokenization, BM25 scoring, exact-phrase boosting, and the
main query_index entry point that returns ranked QueryResult objects.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .document import Document

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BM25_K1 = 1.5
BM25_B = 0.75

STOP_WORDS: set[str] = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "as", "be", "was", "are",
    "were", "been", "has", "have", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "not",
    "no", "so", "if", "then", "than", "that", "this", "these", "those",
    "i", "me", "my", "we", "our", "you", "your", "he", "him", "his",
    "she", "her", "its", "they", "them", "their", "what", "which", "who",
    "when", "where", "why", "how", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "only", "own",
    "same", "just", "also", "very", "too", "up", "out", "about", "into",
}

SNIPPET_CHARS = 200

# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop stop words and short tokens."""
    tokens = _SPLIT_RE.split(text.lower())
    return [t for t in tokens if len(t) >= 2 and t not in STOP_WORDS]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def score_bm25(
    query_tokens: list[str],
    doc: Document,
    avg_dl: float,
    doc_freqs: dict[str, int],
    total_docs: int,
) -> float:
    """Compute BM25 relevance score for a single document."""
    doc_tokens = tokenize(doc.text)
    doc_len = len(doc_tokens)
    if doc_len == 0:
        return 0.0

    tf_map = Counter(doc_tokens)
    score = 0.0

    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        df = doc_freqs.get(qt, 0)
        if df == 0:
            continue

        # IDF component (clamped to avoid negative values)
        idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)

        # TF component with length normalization
        tf_norm = (tf * (BM25_K1 + 1.0)) / (
            tf + BM25_K1 * (1.0 - BM25_B + BM25_B * doc_len / avg_dl)
        )

        score += idf * tf_norm

    return score


def exact_phrase_boost(query: str, doc_text: str) -> float:
    """Return 1.5 if the exact query phrase appears in doc_text, else 1.0."""
    if query.lower() in doc_text.lower():
        return 1.5
    return 1.0


# ---------------------------------------------------------------------------
# Snippet extraction
# ---------------------------------------------------------------------------


def _extract_snippet(text: str, query: str) -> tuple[str, int | None, int | None]:
    """Extract a ~SNIPPET_CHARS window around the best match position.

    Returns (snippet_text, line_start, line_end).
    """
    lower_text = text.lower()
    lower_query = query.lower()

    # Find best match position using query tokens
    query_tokens = tokenize(query)
    best_pos = 0
    best_score = 0

    # Slide a window and score by token overlap
    words = lower_text.split()
    window_size = max(len(query_tokens), 1)
    for i in range(max(len(words) - window_size + 1, 1)):
        window = " ".join(words[i : i + window_size])
        overlap = sum(1 for qt in query_tokens if qt in window)
        if overlap > best_score:
            best_score = overlap
            # Map word index back to character position
            best_pos = lower_text.find(words[i]) if words[i] in lower_text else 0

    # If exact phrase found, center on it
    exact_pos = lower_text.find(lower_query)
    if exact_pos >= 0:
        best_pos = exact_pos

    # Build snippet window
    half = SNIPPET_CHARS // 2
    start = max(0, best_pos - half)
    end = min(len(text), best_pos + half)

    # Expand to line boundaries if possible
    while start > 0 and text[start] != "\n":
        start -= 1
    while end < len(text) and text[end] != "\n":
        end += 1

    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    # Compute line numbers
    line_start = text[:best_pos].count("\n") + 1
    line_end = text[:end].count("\n") + 1

    return snippet, line_start, line_end


# ---------------------------------------------------------------------------
# Query result
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    """A single search result with snippet and score."""

    path: str
    source_category: str
    content_hash: str
    snippet: str
    score: float
    line_start: int | None
    line_end: int | None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "source_category": self.source_category,
            "content_hash": self.content_hash,
            "snippet": self.snippet,
            "score": round(self.score, 4),
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


# ---------------------------------------------------------------------------
# Main query entry point
# ---------------------------------------------------------------------------


def query_index(
    docs: list[Document],
    query: str,
    *,
    max_results: int = 20,
    source_categories: list[str] | None = None,
    path_filter: str | None = None,
) -> list[QueryResult]:
    """Query the document index and return ranked results.

    Parameters
    ----------
    docs:
        The full list of indexed Documents.
    query:
        Free-text search query.
    max_results:
        Maximum number of results to return.
    source_categories:
        If provided, restrict results to these categories.
    path_filter:
        If provided, restrict results to documents whose path contains
        this substring (case-insensitive).
    """
    # Filter documents
    filtered = docs
    if source_categories is not None:
        cat_set = set(source_categories)
        filtered = [d for d in filtered if d.source_category in cat_set]
    if path_filter is not None:
        pf = path_filter.lower()
        filtered = [d for d in filtered if pf in d.path.lower()]

    if not filtered:
        return []

    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    # Pre-compute corpus statistics
    total_docs = len(filtered)
    avg_dl = sum(len(tokenize(d.text)) for d in filtered) / max(total_docs, 1)

    # Document frequency: how many docs contain each token
    doc_freqs: dict[str, int] = {}
    for d in filtered:
        seen = set(tokenize(d.text))
        for token in seen:
            doc_freqs[token] = doc_freqs.get(token, 0) + 1

    # Score each document
    results: list[QueryResult] = []
    for doc in filtered:
        base_score = score_bm25(query_tokens, doc, avg_dl, doc_freqs, total_docs)
        boost = exact_phrase_boost(query, doc.text)
        final_score = base_score * boost

        if final_score > 0:
            snippet, line_start, line_end = _extract_snippet(doc.text, query)
            results.append(
                QueryResult(
                    path=doc.path,
                    source_category=doc.source_category,
                    content_hash=doc.content_hash,
                    snippet=snippet,
                    score=final_score,
                    line_start=line_start,
                    line_end=line_end,
                )
            )

    # Sort descending by score
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:max_results]
