"""Deterministic checks for substantive prose repeated across narrative drafts."""

from __future__ import annotations

import re
from typing import Any


MIN_SUBSTANTIVE_PARAGRAPH_CHARS = 80
BLOCKING_SINGLE_PARAGRAPH_CHARS = 120
BLOCKING_TOTAL_REPEATED_CHARS = 160


def substantive_paragraphs(
    text: str,
    *,
    minimum_characters: int = MIN_SUBSTANTIVE_PARAGRAPH_CHARS,
) -> set[str]:
    """Return normalized prose paragraphs large enough to be substantive."""
    paragraphs: set[str] = set()
    for raw in re.split(r"\n\s*\n", str(text or "")):
        prose = "\n".join(
            line for line in raw.splitlines() if not line.lstrip().startswith("#")
        )
        value = re.sub(r"\s+", "", prose).strip()
        if len(value) < minimum_characters:
            continue
        paragraphs.add(value)
    return paragraphs


def repetition_evidence_from_paragraphs(
    current: set[str],
    previous: set[str],
) -> dict[str, Any]:
    """Describe exact prose shared by two pre-normalized paragraph sets."""
    repeated = sorted(
        current & previous,
        key=lambda value: (-len(value), value),
    )
    repeated_characters = sum(len(value) for value in repeated)
    longest = max((len(value) for value in repeated), default=0)
    blocking = (
        longest >= BLOCKING_SINGLE_PARAGRAPH_CHARS
        or repeated_characters >= BLOCKING_TOTAL_REPEATED_CHARS
    )
    return {
        "blocking": blocking,
        "passage_count": len(repeated),
        "repeated_characters": repeated_characters,
        "longest_passage_characters": longest,
        "samples": [value[:160] for value in repeated[:3]],
    }


def repetition_evidence(current: str, previous: str) -> dict[str, Any]:
    """Describe exact substantive prose shared by two drafts."""
    return repetition_evidence_from_paragraphs(
        substantive_paragraphs(current),
        substantive_paragraphs(previous),
    )
