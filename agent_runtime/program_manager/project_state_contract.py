from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


DEFAULT_TRANSITION_ARTIFACT = "state_transition_proposal.yml"


def load_project_state_templates(agentlab_root: Path) -> dict[str, Any]:
    path = agentlab_root / "config" / "project_state_templates.yml"
    if not path.exists():
        return _fallback_templates()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else _fallback_templates()


def compile_project_state_contract(
    project_brief: dict[str, Any],
    goal: dict[str, Any] | None = None,
    workflow_template: dict[str, Any] | None = None,
    domain_presets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    templates = domain_presets or _fallback_templates()
    universal = templates.get("universal_kernel") or {}
    presets = templates.get("presets") or {}
    selected_key = select_project_state_preset(project_brief, goal, workflow_template, presets)
    preset = presets.get(selected_key) or {}

    return {
        "schema_version": 1,
        "contract_id": f"{project_brief.get('project', 'project')}_fact_state_contract",
        "project": project_brief.get("project"),
        "task_type": project_brief.get("task_type", "unknown"),
        "selected_preset": selected_key,
        "selected_templates": [
            universal.get("template_id", "universal_project_fact_state"),
            preset.get("preset_id", selected_key),
        ],
        "transition_artifact": DEFAULT_TRANSITION_ARTIFACT,
        "universal_kernel": {
            "entity_fields": universal.get("entity_fields") or [],
            "artifact_fields": universal.get("artifact_fields") or [],
            "event_fields": universal.get("event_fields") or [],
            "statuses": universal.get("statuses") or [],
        },
        "entity_types": [str(item) for item in preset.get("entity_types") or []],
        "artifact_types": [str(item) for item in preset.get("artifact_types") or []],
        "event_types": [str(item) for item in preset.get("event_types") or []],
        "state_affecting_outputs": [str(item) for item in preset.get("state_affecting_outputs") or []],
        "dimensions": preset.get("dimensions") or {},
        "status_sequences": preset.get("status_sequences") or {},
        "invariants": list(universal.get("invariants") or []) + list(preset.get("invariants") or []),
        "evidence_policy": {
            "state_change_requires_evidence": True,
            "minimum_evidence_refs": 1,
        },
        "phase_policy": {
            "default_transition_requirement": "required_when_durable_facts_change",
            "proposal_required_when_acceptance_criteria_include": ["project_fact_state_validated"],
        },
    }


def select_project_state_preset(
    project_brief: dict[str, Any],
    goal: dict[str, Any] | None,
    workflow_template: dict[str, Any] | None,
    presets: dict[str, Any],
) -> str:
    candidates = [
        str((project_brief.get("long_project_governance") or {}).get("project_type") or ""),
        str((workflow_template or {}).get("project_type") or ""),
        str(project_brief.get("task_type") or ""),
        str((goal or {}).get("task_type") or ""),
        str(project_brief.get("user_goal") or ""),
        str(project_brief.get("intent_summary") or ""),
    ]
    haystack = " ".join(candidates).lower()
    best_key = ""
    best_score = 0
    for key, preset in presets.items():
        names = [key, str(preset.get("preset_id") or "")]
        names.extend(str(item) for item in preset.get("aliases") or [])
        score = 0
        for name in names:
            lowered = name.lower()
            if not lowered or lowered not in haystack:
                continue
            score += max(1, len(lowered.split("_")) + len(lowered.split()))
            if lowered == str(project_brief.get("task_type") or "").lower():
                score += 2
        if score > best_score:
            best_key = str(key)
            best_score = score
    if best_key:
        return best_key
    if "codebase_build_project" in presets and str(project_brief.get("task_type")) == "coding":
        return "codebase_build_project"
    return "codebase_build_project" if "codebase_build_project" in presets else next(iter(presets), "generic_project")


def build_phase_state_contract(project_brain_dir: Path, phase: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    outputs = [str(item) for item in phase.get("outputs") or phase.get("required_outputs") or []]
    criteria = [str(item) for item in phase.get("acceptance_criteria") or []]
    affecting = sorted(set(outputs).intersection(set(contract.get("state_affecting_outputs") or [])))
    required = bool(
        phase.get("state_transition_required")
        or contract.get("transition_artifact") in outputs
        or any(item in criteria for item in (contract.get("phase_policy") or {}).get("proposal_required_when_acceptance_criteria_include") or [])
    )
    return {
        "contract_ref": "project_state_contract.yml",
        "snapshot_ref": "project_fact_snapshot.yml",
        "events_ref": "project_fact_events.jsonl",
        "project_brain_dir": str(project_brain_dir),
        "transition_artifact": contract.get("transition_artifact", DEFAULT_TRANSITION_ARTIFACT),
        "transition_proposal_required": required,
        "state_affecting_outputs": affecting,
        "policy": contract.get("phase_policy") or {},
    }


def _fallback_templates() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "universal_kernel": {
            "template_id": "universal_project_fact_state",
            "entity_fields": ["entity_id", "entity_type", "status", "facts", "evidence_refs"],
            "artifact_fields": ["artifact_id", "artifact_type", "status", "facts", "evidence_refs"],
            "event_fields": ["event_id", "event_type", "target_kind", "target_type", "target_id", "to_status", "evidence_refs"],
            "statuses": ["planned", "active", "blocked", "resolved", "deprecated", "retired"],
            "invariants": [{"invariant_id": "evidence_required_for_state_change"}],
        },
        "presets": {
            "codebase_build_project": {
                "preset_id": "codebase_build_state",
                "aliases": ["coding", "software"],
                "entity_types": ["module", "api"],
                "artifact_types": ["repo_context", "patch_plan", "test_evidence"],
                "event_types": ["create", "revise", "retire", "restore", "migrate", "verify"],
                "state_affecting_outputs": ["repo_context", "patch_plan", "test_evidence"],
                "invariants": [],
            }
        },
    }
