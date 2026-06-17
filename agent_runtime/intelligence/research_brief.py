from __future__ import annotations

"""Research brief generation for AgentLab web intelligence.

Takes a list of evidence dicts (typically produced by the fetcher and
extractor pipeline) and assembles them into a structured brief with
claims, citations, and an evidence-sufficiency flag.
"""

import hashlib
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Citation:
    """A single citation backing one or more claims."""

    citation_id: str
    url: str
    title: str
    snippet: str
    source_quality_score: int = 0


@dataclass(frozen=True)
class Claim:
    """A factual claim derived from the collected evidence."""

    text: str
    evidence_ids: list[str]


@dataclass
class ResearchBrief:
    """Complete research brief for a single topic."""

    topic: str
    summary: str
    claims: list[Claim]
    citations: list[Citation]
    insufficient_evidence: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_citation_id(url: str, index: int) -> str:
    """Generate a short, stable citation ID from a URL and its position."""
    digest = hashlib.sha256(f"{url}::{index}".encode("utf-8")).hexdigest()
    return f"cite-{digest[:8]}"


def _truncate(text: str, max_len: int = 240) -> str:
    """Return *text* truncated to *max_len* characters with an ellipsis."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


# ---------------------------------------------------------------------------
# Brief generation
# ---------------------------------------------------------------------------

_MINIMUM_EVIDENCE = 3


def generate_brief(
    topic: str,
    evidence: list[dict],
) -> ResearchBrief:
    """Assemble a ``ResearchBrief`` from a list of evidence dicts.

    Each dict in *evidence* should contain at least:
    - ``"url"`` (str)
    - ``"title"`` (str, optional)
    - ``"body_text"`` (str)
    - ``"source_quality_score"`` (int, optional, default 0)

    When fewer than ``_MINIMUM_EVIDENCE`` (3) entries are supplied the
    brief is flagged with ``insufficient_evidence = True`` and the
    summary notes the shortfall.
    """
    citations: list[Citation] = []
    claims: list[Claim] = []
    summary_parts: list[str] = []
    insufficient = False

    # --- Build citations ----------------------------------------------------
    for idx, ev in enumerate(evidence):
        url = str(ev.get("url", ""))
        title = str(ev.get("title", "") or "(untitled)")
        body = str(ev.get("body_text", "") or "")
        quality = int(ev.get("source_quality_score", 0))
        cid = _make_citation_id(url, idx)

        citations.append(Citation(
            citation_id=cid,
            url=url,
            title=title,
            snippet=_truncate(body),
            source_quality_score=quality,
        ))

        # Generate one claim per evidence entry (simplified heuristic)
        if body:
            first_sentence = body.split(".")[0].strip()
            if first_sentence:
                claims.append(Claim(
                    text=first_sentence,
                    evidence_ids=[cid],
                ))

    # --- Insufficiency check ------------------------------------------------
    if len(evidence) < _MINIMUM_EVIDENCE:
        insufficient = True
        summary_parts.append(
            f"Insufficient evidence: only {len(evidence)} source(s) "
            f"available (minimum {_MINIMUM_EVIDENCE} recommended)."
        )

    # --- Summary construction -----------------------------------------------
    summary_parts.append(f"Research brief for: {topic}.")

    if citations:
        avg_score = (
            sum(c.source_quality_score for c in citations) / len(citations)
        )
        summary_parts.append(
            f"Collected {len(citations)} citation(s) "
            f"with average quality score {avg_score:.0f}/100."
        )

    if claims:
        summary_parts.append(f"Derived {len(claims)} claim(s) from evidence.")
    else:
        summary_parts.append("No claims could be derived from the evidence.")

    summary = " ".join(summary_parts)

    return ResearchBrief(
        topic=topic,
        summary=summary,
        claims=claims,
        citations=citations,
        insufficient_evidence=insufficient,
    )
