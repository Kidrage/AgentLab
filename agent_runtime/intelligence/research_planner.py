from __future__ import annotations

"""Research query planner for AgentLab web intelligence.

Given a free-text topic, the planner generates 3-5 structured search
queries and a list of expected source types.  The logic is purely
deterministic — no LLM call is required.
"""

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlannedSource:
    """Describes the kind of source a particular query is expected to find."""

    query: str
    expected_type: str   # e.g. "docs", "tutorial", "reference", "discussion"


@dataclass
class ResearchPlan:
    """Complete plan for a single research topic."""

    topic: str
    queries: list[str]
    planned_sources: list[PlannedSource]


# ---------------------------------------------------------------------------
# Keyword extraction helpers
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "as", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "shall", "should", "may", "might", "can",
    "could", "this", "that", "these", "those", "what", "which", "who",
    "how", "when", "where", "why", "all", "each", "every", "both",
    "few", "more", "most", "other", "some", "such", "no", "not", "only",
    "same", "so", "than", "too", "very", "just", "about", "into",
    "over", "after", "before", "between", "under", "again", "then",
    "once", "here", "there", "up", "out", "off", "down",
})


def _extract_keywords(topic: str, max_keywords: int = 6) -> list[str]:
    """Return up to *max_keywords* meaningful words from *topic*.

    Strips punctuation, lower-cases, removes stop words and short tokens.
    """
    cleaned = re.sub(r"[^\w\s]", " ", topic.lower())
    tokens = cleaned.split()
    keywords = [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique[:max_keywords]


# ---------------------------------------------------------------------------
# Query templates
# ---------------------------------------------------------------------------

_QUERY_TEMPLATES: list[tuple[str, str]] = [
    ("{kw} documentation", "docs"),
    ("{kw} tutorial guide", "tutorial"),
    ("{kw} best practices", "reference"),
    ("{kw} example code", "tutorial"),
    ("{kw} troubleshooting common issues", "discussion"),
    ("{kw} specification standard", "reference"),
    ("{kw} comparison alternatives", "discussion"),
]


def _build_queries(
    keywords: list[str],
    min_queries: int = 3,
    max_queries: int = 5,
) -> list[tuple[str, str]]:
    """Generate (query, expected_type) pairs from *keywords*.

    Returns between *min_queries* and *max_queries* entries.
    """
    if not keywords:
        return [("general research query", "reference")]

    joined = " ".join(keywords[:4])
    results: list[tuple[str, str]] = []

    for template, etype in _QUERY_TEMPLATES:
        query = template.format(kw=joined)
        results.append((query, etype))
        if len(results) >= max_queries:
            break

    # Ensure minimum
    while len(results) < min_queries:
        results.append((f"{joined} reference", "reference"))

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_research(
    topic: str,
    context: dict | None = None,
) -> ResearchPlan:
    """Generate a ``ResearchPlan`` for *topic*.

    Parameters
    ----------
    topic:
        Free-text description of the subject to research.
    context:
        Optional extra context dict.  Recognised keys:
        - ``"focus"``: a sub-area to bias queries towards.
        - ``"max_queries"``: override the default upper bound.

    Returns
    -------
    ResearchPlan with 3-5 queries and planned source descriptions.
    """
    context = context or {}
    max_q = int(context.get("max_queries", 5))
    focus = str(context.get("focus", ""))

    # Incorporate focus into the keyword set
    effective_topic = f"{topic} {focus}".strip() if focus else topic
    keywords = _extract_keywords(effective_topic)

    raw_queries = _build_queries(keywords, max_queries=max_q)

    queries = [q for q, _ in raw_queries]
    planned_sources = [
        PlannedSource(query=q, expected_type=et) for q, et in raw_queries
    ]

    return ResearchPlan(
        topic=topic,
        queries=queries,
        planned_sources=planned_sources,
    )
