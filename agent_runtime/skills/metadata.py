"""R2: Skill Registry Metadata Governance.

Extends the external skill registry with lifecycle status, input/output
schemas, quality tracking, and governance validation. Fully backward
compatible with schema_version 1 registries.

This module is metadata-only and never executes external skills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

VALID_LIFECYCLE_STATUSES = frozenset({
    "draft",
    "candidate",
    "pending_review",
    "staging",
    "active",
    "disabled",
    "rejected",
    "deprecated",
})

VALID_SOURCES = frozenset({
    "agentlab_internal",
    "ecc",
    "anysearch",
    "codegraph",
    "custom_local",
    "unknown",
})

VALID_SOURCE_TYPES = frozenset({
    "internal_skill",
    "external_agent_pack",
    "external_provider",
    "local_script",
    "documentation_only",
    "external_search_provider",
    "external_cli_tool",
    "external_skill",
})

VALID_ARTIFACT_TYPES = frozenset({
    "text", "repo", "url", "image", "pdf", "audio", "video",
    "screenshot", "json", "yaml", "markdown", "patch", "report",
    "index", "candidate",
})

VALID_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})

VALID_BILLING_MODES = frozenset({
    "local", "api_model", "external_harness", "external_api_or_anonymous",
    "local_resource", "unknown",
})

VALID_COST_TIERS = frozenset({"free", "low", "medium", "high", "unknown"})

VALID_DISTILLATION_COMPAT = frozenset({
    "review_required", "yes", "no",
})


@dataclass
class SkillInputs:
    artifacts: list[str] = field(default_factory=list)
    context_required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": list(self.artifacts),
            "context_required": list(self.context_required),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillInputs:
        if not data:
            return cls()
        return cls(
            artifacts=list(data.get("artifacts") or []),
            context_required=list(data.get("context_required") or []),
        )


@dataclass
class SkillOutputs:
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"artifacts": list(self.artifacts)}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillOutputs:
        if not data:
            return cls()
        return cls(artifacts=list(data.get("artifacts") or []))


@dataclass
class SkillQuality:
    success_count: int = 0
    failure_count: int = 0
    last_used_at: str | None = None
    quality_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_used_at": self.last_used_at,
            "quality_score": self.quality_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillQuality:
        if not data:
            return cls()
        return cls(
            success_count=int(data.get("success_count") or 0),
            failure_count=int(data.get("failure_count") or 0),
            last_used_at=data.get("last_used_at"),
            quality_score=data.get("quality_score"),
        )


def default_metadata() -> dict[str, Any]:
    return {
        "lifecycle_status": "draft",
        "inputs": {"artifacts": [], "context_required": []},
        "outputs": {"artifacts": []},
        "quality": {
            "success_count": 0,
            "failure_count": 0,
            "last_used_at": None,
            "quality_score": None,
        },
    }


def enrich_skill_dict(skill: dict[str, Any]) -> dict[str, Any]:
    """Add R2 metadata fields to a skill dict, preserving existing values."""
    skill.setdefault("lifecycle_status", "draft")
    skill.setdefault("inputs", {"artifacts": [], "context_required": []})
    skill.setdefault("outputs", {"artifacts": []})
    skill.setdefault("quality", {
        "success_count": 0,
        "failure_count": 0,
        "last_used_at": None,
        "quality_score": None,
    })
    return skill


def validate_skill_metadata(skill: dict[str, Any]) -> list[str]:
    """Validate R2 metadata fields. Returns list of error messages."""
    errors: list[str] = []
    skill_id = skill.get("skill_id") or "<unknown>"

    status = str(skill.get("lifecycle_status") or "draft").strip()
    if status not in VALID_LIFECYCLE_STATUSES:
        errors.append(f"{skill_id}: invalid lifecycle_status '{status}'")

    enabled = skill.get("enabled", False)
    if status == "active" and not enabled:
        errors.append(f"{skill_id}: lifecycle_status is 'active' but enabled is false")
    if enabled and status not in ("active", "staging"):
        errors.append(
            f"{skill_id}: enabled=true requires lifecycle_status 'active' or 'staging', "
            f"got '{status}'"
        )

    source = str(skill.get("source") or "").strip().lower()
    if source not in VALID_SOURCES and source not in {
        "external_skill_pack", "external_search_provider",
    }:
        errors.append(f"{skill_id}: unrecognized source '{source}'")

    if source not in ("agentlab_internal",) and enabled:
        errors.append(f"{skill_id}: external source '{source}' must default to enabled=false")

    license_info = skill.get("license") or {}
    license_name = str(license_info.get("name") or "unknown").strip().lower()
    if license_name in ("", "unknown", "proprietary"):
        compat = str(
            license_info.get("compatible_for_internal_distillation") or "review_required"
        ).strip().lower()
        if compat != "no":
            if not license_info.get("license_review_required"):
                errors.append(
                    f"{skill_id}: unknown license requires review "
                    f"(license_review_required should be true)"
                )

    inputs = skill.get("inputs") or {}
    for art in inputs.get("artifacts") or []:
        if art not in VALID_ARTIFACT_TYPES:
            errors.append(f"{skill_id}: invalid input artifact type '{art}'")

    outputs = skill.get("outputs") or {}
    for art in outputs.get("artifacts") or []:
        if art not in VALID_ARTIFACT_TYPES:
            errors.append(f"{skill_id}: invalid output artifact type '{art}'")

    risk = skill.get("risk") or {}
    level = str(risk.get("level") or "medium").lower()
    if level not in VALID_RISK_LEVELS:
        errors.append(f"{skill_id}: invalid risk level '{level}'")

    return errors


def assert_dispatchable_with_lifecycle(registry: dict[str, Any], skill_id: str) -> dict[str, Any]:
    """Check that a skill is dispatchable considering lifecycle status."""
    skill = None
    for s in registry.get("external_skills", []) or []:
        if s.get("skill_id") == skill_id:
            skill = s
            break
    if not skill:
        raise KeyError(f"Unknown external skill: {skill_id}")

    status = str(skill.get("lifecycle_status") or "draft").strip()
    if status in ("pending_review", "draft", "candidate", "rejected", "deprecated"):
        raise PermissionError(
            f"Skill '{skill_id}' has lifecycle_status '{status}' and cannot execute"
        )
    if not skill.get("enabled", False):
        raise PermissionError(f"Skill '{skill_id}' is disabled")
    if status == "disabled":
        raise PermissionError(f"Skill '{skill_id}' has lifecycle_status 'disabled'")

    return skill


@dataclass
class RegistrySummary:
    total: int = 0
    by_lifecycle: dict[str, int] = field(default_factory=dict)
    by_source: dict[str, int] = field(default_factory=dict)
    by_risk_level: dict[str, int] = field(default_factory=dict)
    active_skills: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)
    blocked_or_review_required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_lifecycle": dict(self.by_lifecycle),
            "by_source": dict(self.by_source),
            "by_risk_level": dict(self.by_risk_level),
            "active_skills": list(self.active_skills),
            "candidates": list(self.candidates),
            "blocked_or_review_required": list(self.blocked_or_review_required),
        }


def build_registry_summary(registry: dict[str, Any]) -> RegistrySummary:
    """Build a summary of the registry for governance reporting."""
    summary = RegistrySummary()
    skills = registry.get("external_skills", []) or []
    summary.total = len(skills)

    for skill in skills:
        sid = skill.get("skill_id") or "<unknown>"
        status = str(skill.get("lifecycle_status") or "draft").strip()
        source = str(skill.get("source") or "unknown").strip()
        risk_level = str((skill.get("risk") or {}).get("level") or "medium").lower()

        summary.by_lifecycle[status] = summary.by_lifecycle.get(status, 0) + 1
        summary.by_source[source] = summary.by_source.get(source, 0) + 1
        summary.by_risk_level[risk_level] = summary.by_risk_level.get(risk_level, 0) + 1

        if status == "active" and skill.get("enabled"):
            summary.active_skills.append(sid)
        if status == "candidate":
            summary.candidates.append(sid)

        license_info = skill.get("license") or {}
        review_required = bool(license_info.get("license_review_required"))
        if status in ("rejected", "deprecated", "disabled") or review_required:
            summary.blocked_or_review_required.append(sid)

    return summary
