"""Long-project governance helpers shared by planning and execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


LONG_PROJECT_TYPES = {
    "longform_text_project",
    "codebase_build_project",
    "video_generation_project",
}


def load_long_project_governance(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "long_project_governance.yml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def governance_for_project_type(agentlab_root: Path, project_type: str) -> dict[str, Any]:
    config = load_long_project_governance(agentlab_root)
    constitutions = config.get("project_constitutions") or {}
    constitution = constitutions.get(project_type) or {}
    return {
        "enabled": bool(constitution),
        "project_type": project_type,
        "brain_workflow": config.get("hermes_brain_workflow") or [],
        "handoff_contract_fields": config.get("handoff_contract_fields") or [],
        "dispatch_gates": config.get("dispatch_gates") or [],
        "constitution": constitution,
        "required_plan_artifacts": [
            item.get("artifact_id")
            for item in constitution.get("required_artifacts") or []
            if item.get("artifact_id")
        ],
        "continuity_acceptance": constitution.get("continuity_acceptance") or [],
        "frontdesk_rules": config.get("frontdesk_rules") or [],
    }


def build_project_governance_pack(
    agentlab_root: Path,
    project_type: str,
    project_root: Path | None = None,
    *,
    max_paths_per_artifact: int = 8,
) -> dict[str, Any]:
    base = governance_for_project_type(agentlab_root, project_type)
    constitution = base.get("constitution") or {}
    artifact_status = []
    must_read: list[str] = []
    missing_facts: list[dict[str, str]] = []

    for artifact in constitution.get("required_artifacts") or []:
        artifact_id = artifact.get("artifact_id")
        patterns = [str(item) for item in artifact.get("patterns") or []]
        paths = _discover_paths(project_root, patterns, max_paths_per_artifact)
        status = "present" if paths else ("not_checked" if project_root is None else "missing")
        artifact_status.append(
            {
                "artifact_id": artifact_id,
                "status": status,
                "paths": paths,
                "gate": artifact.get("gate", "required_before_dispatch"),
            }
        )
        if paths:
            must_read.extend(paths)
        elif project_root is not None:
            missing_facts.append(
                {
                    "fact": str(artifact_id),
                    "reason": str(artifact.get("missing_reason") or "required long-project artifact is absent"),
                }
            )

    configured_must_read = [str(item) for item in constitution.get("must_read_patterns") or []]
    if project_root is None:
        must_read.extend(configured_must_read)
    else:
        must_read.extend(_discover_paths(project_root, configured_must_read, 32))
    base.update(
        {
            "artifact_status": artifact_status,
            "must_read_artifacts": sorted(set(must_read)),
            "missing_facts": missing_facts,
            "gap_cards": [
                {
                    "gap_id": f"missing_{item['fact']}",
                    "question": item["reason"],
                    "blocks_dispatch": True,
                }
                for item in missing_facts
            ],
        }
    )
    return base


def infer_project_root_from_run_dir(run_dir: Path | None) -> Path | None:
    if run_dir is None:
        return None
    if run_dir.parent.name == "runs":
        return run_dir.parent.parent
    return run_dir


def plan_self_check(phase: dict[str, Any]) -> dict[str, Any]:
    current = phase.get("self_check")
    if isinstance(current, dict) and "passed" in current:
        return current
    missing = phase.get("missing_facts") or []
    return {
        "passed": not bool(missing),
        "checks": [
            "plan_status_present",
            "missing_facts_reviewed",
            "must_read_artifacts_listed",
            "revision_log_preserved",
        ],
    }


def assert_dispatch_allowed(phase: dict[str, Any]) -> None:
    self_check = phase.get("self_check")
    if isinstance(self_check, dict) and self_check.get("passed") is False:
        raise ValueError("Plan self-check has not passed; refusing dispatch.")
    plan_status = phase.get("plan_status")
    if plan_status and plan_status not in {"ready", "approved", "legacy_ready"}:
        raise ValueError(f"Plan status {phase.get('plan_status')} cannot be dispatched.")


def _discover_paths(project_root: Path | None, patterns: list[str], limit: int) -> list[str]:
    if project_root is None or not project_root.exists():
        return []
    found: list[str] = []
    for pattern in patterns:
        for path in sorted(project_root.glob(pattern)):
            if len(found) >= limit:
                return found
            if path.is_file():
                found.append(str(path.relative_to(project_root)))
            elif path.is_dir() and not any(str(path.relative_to(project_root)) == item for item in found):
                found.append(str(path.relative_to(project_root)) + "/")
    return found
