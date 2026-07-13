"""Domain classifier — rule-based task domain detection from prompt text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def load_domain_keywords(config_path: Path | None = None) -> dict[str, Any]:
    """Load domain keyword config. Returns empty dict on failure (no crash)."""
    if config_path is None:
        config_path = _default_config_path()
    if not config_path.exists():
        return {}
    import yaml

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return data.get("domain_keywords", {}) if isinstance(data, dict) else {}


def classify_domain(
    prompt: str,
    domain_keywords: dict[str, Any] | None = None,
) -> str:
    """Classify a rough user prompt into a task domain using keyword matching.

    Returns one of: coding, creative_longform, video_generation, research,
    document_processing, audio_music, multimodal, local_ops, unknown.
    """
    if domain_keywords is None:
        domain_keywords = load_domain_keywords()
    lowered = prompt.lower()
    scores: dict[str, int] = {}
    for domain, entry in domain_keywords.items():
        if not isinstance(entry, dict):
            continue
        keywords = entry.get("keywords", [])
        score = 0
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            # longer keyword matches count more
            normalized = kw.lower().strip()
            if not normalized:
                continue
            pattern = re.escape(normalized)
            if re.match(r"[a-z0-9_]", normalized[0]):
                pattern = rf"(?<![a-z0-9_]){pattern}"
            if re.match(r"[a-z0-9_]", normalized[-1]):
                pattern = rf"{pattern}(?![a-z0-9_])"
            if re.search(pattern, lowered):
                score += len(kw.split())
        if score > 0:
            scores[domain] = score
    if not scores:
        return "unknown"
    # return domain with highest keyword match score
    return max(scores, key=lambda k: scores[k])


def _default_config_path() -> Path:
    return Path(__file__).resolve().parents[2] / "config" / "mission_compiler_v2.yml"
