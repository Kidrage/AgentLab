"""Risk classifier — detects risk flags from prompt text and project type."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def classify_risks(
    prompt: str,
    project_type: str,
    project_types: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify risks from prompt text and project type definition.

    Returns dict with:
      - risk_flags: combined list of risk flag strings
      - non_goal_hits: detected non-goal patterns in the prompt
      - constraint_hits: detected constraint patterns in the prompt
      - safety_ok: whether no non-goal patterns were detected
    """
    if project_types is None:
        from agent_runtime.brain.project_type_classifier import load_project_types
        project_types = load_project_types()
    typedef = project_types.get(project_type, project_types.get("unknown_project", {}))
    risk_flags = list(typedef.get("risk_flags", []))

    # Load non-goal and constraint patterns from compiler config
    compiler_config = _load_compiler_config()
    non_goal_hits = _match_patterns(prompt, compiler_config.get("non_goal_patterns", []))
    constraint_hits = _match_patterns(prompt, compiler_config.get("constraint_patterns", []))

    return {
        "risk_flags": risk_flags,
        "non_goal_hits": non_goal_hits,
        "constraint_hits": constraint_hits,
        "safety_ok": len(non_goal_hits) == 0,
    }


def _match_patterns(text: str, patterns: list[str]) -> list[str]:
    """Return patterns that appear in text (case-insensitive substring match)."""
    lowered = text.lower()
    hits: list[str] = []
    for pattern in patterns:
        if pattern.lower() in lowered:
            hits.append(pattern)
    return hits


def _load_compiler_config() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[2] / "config" / "mission_compiler_v2.yml"
    if not path.exists():
        return {}
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}
