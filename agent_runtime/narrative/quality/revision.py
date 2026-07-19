"""Compile audit findings into bounded, executable revision contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


def _strings(values: Iterable[str], *, field: str) -> list[str]:
    result = [str(value).strip() for value in values if str(value).strip()]
    if not result:
        raise ValueError(f"{field} must not be empty")
    return result


def compile_scene_revision_contract(
    finding: Mapping[str, Any],
    *,
    must_preserve: Iterable[str],
    allowed_freedom: str,
    causal_requirements: Iterable[str],
    character_knowledge_before: Iterable[str],
    character_knowledge_after: Iterable[str],
    decision_cost: str,
    new_information: str,
    forbidden_regressions: Iterable[str],
) -> dict[str, object]:
    """Turn one located finding into a scene-first Writer contract."""
    required = (
        "chapter_id",
        "target_scene",
        "problem_type",
        "evidence",
        "revision_target",
    )
    missing = [field for field in required if not finding.get(field)]
    if missing:
        raise ValueError("finding missing required fields: " + ",".join(missing))
    problem_type = str(finding["problem_type"])
    contract: dict[str, object] = {
        "schema_version": 1,
        "chapter_id": int(finding["chapter_id"]),
        "target_scene": str(finding["target_scene"]),
        "rewrite_scope": (
            "chapter"
            if problem_type in {"structural_failure", "chapter_structure_failure"}
            else "scene"
        ),
        "problem_type": problem_type,
        "evidence": str(finding["evidence"]),
        "must_preserve": _strings(must_preserve, field="must_preserve"),
        "must_change": [str(finding["revision_target"]).strip()],
        "allowed_freedom": str(allowed_freedom).strip(),
        "causal_requirements": _strings(
            causal_requirements,
            field="causal_requirements",
        ),
        "character_knowledge_before": _strings(
            character_knowledge_before,
            field="character_knowledge_before",
        ),
        "character_knowledge_after": _strings(
            character_knowledge_after,
            field="character_knowledge_after",
        ),
        "decision_cost": str(decision_cost).strip(),
        "new_information": str(new_information).strip(),
        "forbidden_regressions": _strings(
            forbidden_regressions,
            field="forbidden_regressions",
        ),
    }
    for field in ("allowed_freedom", "decision_cost", "new_information"):
        if not contract[field]:
            raise ValueError(f"{field} must not be empty")
    contract["revision_contract_id"] = "rev-" + hashlib.sha256(
        json.dumps(contract, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:24]
    return contract
