"""Skill incubation candidate generation.

This module proposes internal skill candidates from external skill metadata and
usage signals. It never writes copied third-party source code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

from atomic_io import atomic_write_yaml, safe_read_yaml

try:
    from skills.risk import license_requires_review
except ImportError:  # pragma: no cover
    from .risk import license_requires_review


POLICY_REL_PATH = Path("config/skill_incubation_policy.yml")


@dataclass
class InternalSkillCandidate:
    candidate_id: str
    derived_from: list[str]
    derivation_type: str
    status: str
    capability: list[str]
    reason: list[str]
    proposed_internal_skill: dict[str, Any]
    safety: dict[str, Any]
    budget: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "derived_from": self.derived_from,
            "derivation_type": self.derivation_type,
            "status": self.status,
            "capability": self.capability,
            "reason": self.reason,
            "proposed_internal_skill": self.proposed_internal_skill,
            "safety": self.safety,
            "budget": self.budget,
        }


def default_incubation_policy() -> dict[str, Any]:
    return {
        "skill_incubation": {
            "enabled": True,
            "budget": {
                "max_incubation_cost_usd_per_task": 0.03,
                "max_incubation_tokens_per_task": 12000,
                "max_candidates_per_task": 3,
            },
            "triggers": {
                "min_successful_uses": 2,
                "min_quality_score": 0.75,
                "trigger_on_external_dependency_risk": True,
                "trigger_on_high_reuse_potential": True,
            },
            "allowed_outputs": ["skill_summary", "internal_skill_candidate", "checklist", "adapter_notes", "risk_notes"],
            "forbidden_outputs": ["copied_external_source_code", "copied_incompatible_license_text", "secrets", "private_tokens"],
            "review_required": True,
        }
    }


def load_incubation_policy(agentlab_root: Path, path: Path | None = None) -> dict[str, Any]:
    data = safe_read_yaml(path or (agentlab_root / POLICY_REL_PATH), default={}) or {}
    if not isinstance(data, dict) or not data:
        data = default_incubation_policy()
    data.setdefault("skill_incubation", default_incubation_policy()["skill_incubation"])
    return data


def write_internal_skill_candidates(path: Path, candidates: list[InternalSkillCandidate | dict[str, Any]], warnings: list[str] | None = None) -> Path:
    data = {
        "schema_version": 1,
        "warnings": list(warnings or []),
        "candidates": [c.to_dict() if isinstance(c, InternalSkillCandidate) else c for c in candidates],
    }
    atomic_write_yaml(path, data)
    return path


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "skill"


def _usage_counts(usage_ledger: dict[str, Any], min_quality: float) -> dict[str, dict[str, Any]]:
    counts: dict[str, dict[str, Any]] = {}
    for entry in usage_ledger.get("entries", []) or []:
        skill_id = entry.get("skill_id")
        if not skill_id:
            continue
        item = counts.setdefault(skill_id, {"planned_used": 0, "successful": 0, "events": []})
        if entry.get("event") in {"planned", "used"}:
            item["planned_used"] += 1
        if entry.get("event") == "used" and entry.get("success") is True:
            score = entry.get("quality_score")
            if score is None or float(score) >= min_quality:
                item["successful"] += 1
        item["events"].append(entry)
    return counts


def propose_internal_skill_candidates(
    registry: dict[str, Any],
    usage_ledger: dict[str, Any],
    policy: dict[str, Any],
    task_context: dict[str, Any] | None = None,
) -> list[InternalSkillCandidate]:
    cfg = policy.get("skill_incubation", policy)
    if not cfg.get("enabled", True):
        return []
    budget = cfg.get("budget", {}) or {}
    triggers = cfg.get("triggers", {}) or {}
    max_candidates = int(budget.get("max_candidates_per_task", 3))
    min_successful = int(triggers.get("min_successful_uses", 2))
    min_quality = float(triggers.get("min_quality_score", 0.75))
    counts = _usage_counts(usage_ledger, min_quality)
    common_tasks = {"repo_patch", "repo_profile", "security_review"}
    candidates: list[InternalSkillCandidate] = []

    for skill in registry.get("external_skills", []) or []:
        skill_id = skill.get("skill_id")
        if not skill_id or skill.get("source") == "agentlab_internal":
            continue
        stats = counts.get(skill_id, {"planned_used": 0, "successful": 0})
        reasons: list[str] = []
        if stats.get("successful", 0) >= min_successful or stats.get("planned_used", 0) >= min_successful:
            reasons.append("external skill appears useful for repeated tasks")
        risk_reasons = set((skill.get("risk") or {}).get("reasons") or [])
        if triggers.get("trigger_on_external_dependency_risk", True) and ("external_dependency_risk" in risk_reasons or "external_prompt_dependency" in risk_reasons):
            reasons.append("reduces dependency on external provider or prompt pack")
        if triggers.get("trigger_on_high_reuse_potential", True) and common_tasks.intersection(skill.get("suitable_task_types") or []):
            reasons.append("high reuse potential for common AgentLab task types")
        if not reasons:
            continue

        caps = list(skill.get("capabilities") or ["workflow_summary"])
        candidate_slug = _slug(str(skill_id).replace(".", "_"))
        title_base = str(skill.get("display_name") or skill_id).replace("ECC ", "").strip()
        license_review = license_requires_review(skill.get("license"))
        candidates.append(InternalSkillCandidate(
            candidate_id=f"internal.{candidate_slug}_candidate",
            derived_from=[skill_id],
            derivation_type="method_summary",
            status="proposed",
            capability=caps,
            reason=reasons,
            proposed_internal_skill={
                "title": f"{title_base} Checklist",
                "target_path": f"skills/internal/{candidate_slug.replace('_', '-')}/SKILL.md",
                "summary": "A local AgentLab skill candidate distilled from repeated useful external workflows.",
            },
            safety={
                "source_code_copied": False,
                "license_review_required": bool(license_review),
                "human_review_required": bool(cfg.get("review_required", True)),
            },
            budget={
                "estimated_tokens": min(4000, int(budget.get("max_incubation_tokens_per_task", 12000))),
                "estimated_cost_usd": None,
            },
        ))
        if len(candidates) >= max_candidates:
            break
    return candidates
