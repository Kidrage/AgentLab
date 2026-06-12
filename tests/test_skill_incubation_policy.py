from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from skills.incubation import default_incubation_policy, propose_internal_skill_candidates


def _registry(count: int = 1) -> dict:
    skills = []
    for idx in range(count):
        skills.append({
            "skill_id": f"ecc.planner{idx}",
            "source": "ecc",
            "display_name": f"ECC Planner {idx}",
            "capabilities": ["planning", "repo_patch_strategy"],
            "suitable_task_types": ["repo_patch"],
            "risk": {"level": "medium", "reasons": ["external_dependency_risk"], "requires_approval": True},
            "license": {"name": "unknown", "compatible_for_internal_distillation": "review_required"},
        })
    return {"external_skills": skills}


def _usage(skill_id: str = "ecc.planner0") -> dict:
    return {"entries": [
        {"skill_id": skill_id, "event": "used", "success": True, "quality_score": 0.9},
        {"skill_id": skill_id, "event": "used", "success": True, "quality_score": 0.8},
    ]}


def test_incubation_proposes_candidate_after_repeated_use() -> None:
    candidates = propose_internal_skill_candidates(_registry(), _usage(), default_incubation_policy())
    assert candidates
    assert candidates[0].derived_from == ["ecc.planner0"]


def test_incubation_marks_source_code_not_copied() -> None:
    candidate = propose_internal_skill_candidates(_registry(), _usage(), default_incubation_policy())[0].to_dict()
    assert candidate["safety"]["source_code_copied"] is False


def test_incubation_respects_max_candidates() -> None:
    policy = default_incubation_policy()
    policy["skill_incubation"]["budget"]["max_candidates_per_task"] = 2
    usage = {"entries": []}
    for idx in range(5):
        usage["entries"].extend(_usage(f"ecc.planner{idx}")["entries"])
    candidates = propose_internal_skill_candidates(_registry(5), usage, policy)
    assert len(candidates) == 2


def test_incubation_unknown_license_requires_review() -> None:
    candidate = propose_internal_skill_candidates(_registry(), _usage(), default_incubation_policy())[0].to_dict()
    assert candidate["safety"]["license_review_required"] is True
