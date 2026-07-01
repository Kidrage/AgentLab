from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.operator_os import (
    build_operator_action_catalog,
    build_operator_state,
    validate_operator_action,
)
from agent_runtime.operator_os.stage_scope import active_stage_scope
from agent_runtime.ops_console.status_api import build_ops_console_snapshot


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _project(root: Path, project: str = "Crown_of_Ash") -> Path:
    project_root = root / "projects" / project
    brain = project_root / "project_brain"
    brain.mkdir(parents=True)
    (project_root / "PROJECT_HANDOFF.md").write_text("# Handoff\n", encoding="utf-8")
    _write_yaml(project_root / "project_artifact_index.yml", {"artifacts": []})
    _write_yaml(brain / "project_fact_snapshot.yml", {"project": project, "event_count": 2})
    _write_yaml(
        brain / "acceptance_history.yml",
        {
            "entries": [
                {
                    "phase_id": "phase_1_foundation",
                    "accepted": True,
                    "verdict": "PASS",
                    "recommended_next_action": "next_phase",
                    "evidence_files": ["world_bible.yml"],
                    "recorded_at": "2026-07-01T00:00:00+00:00",
                }
            ]
        },
    )
    _write_yaml(
        brain / "next_actions.yml",
        {
            "next_phase_id": "phase_2_draft_batch",
            "next_action": "prepare_phase_task_packet",
            "reason": "first unaccepted roadmap phase",
        },
    )
    return project_root


def test_active_stage_scope_freezes_current_m3_label() -> None:
    scope = active_stage_scope()
    assert scope["active_labels"]["M3"] == "Operator OS / Transparent Control Plane"
    assert scope["active_labels"]["M4"] == "Project-to-Revenue OS"
    assert "business_contract" in scope["m3_must_not_implement"]


def test_m3_alignment_docs_warn_about_historical_labels() -> None:
    root = Path(__file__).resolve().parents[1]
    alignment = (root / "docs" / "M3_0_OPERATOR_OS_ALIGNMENT.md").read_text(encoding="utf-8")
    review = (root / "docs" / "M3_UPGRADE_PLAN_REVIEW.md").read_text(encoding="utf-8")
    scope = (root / "docs" / "M_SERIES_SCOPE.md").read_text(encoding="utf-8")

    assert "M3 means Operator OS / Transparent Control Plane" in alignment
    assert "M4 means Project-to-Revenue OS" in alignment
    assert "M3-0: Operator OS Alignment" in review
    assert "| M3 | Operator OS / Transparent Control Plane |" in scope


def test_operator_state_derives_progress_from_project_brain(tmp_path: Path) -> None:
    _project(tmp_path)

    state = build_operator_state(tmp_path, "Crown_of_Ash")

    assert state["stage"] == "M3_OPERATOR_OS"
    assert state["source_policy"]["directory_layout_is_not_truth"] is True
    assert state["project"]["status"] == "ready"
    assert state["phase_progress"]["accepted_phase_ids"] == ["phase_1_foundation"]
    assert state["phase_progress"]["latest_acceptance"]["evidence_files"] == ["world_bible.yml"]
    assert state["next_action"]["data"]["next_phase_id"] == "phase_2_draft_batch"
    assert state["facts"]["event_count"] == 2


def test_operator_state_reports_missing_brain_inputs(tmp_path: Path) -> None:
    brain = tmp_path / "projects" / "NovelGen" / "project_brain"
    brain.mkdir(parents=True)
    _write_yaml(brain / "acceptance_history.yml", {"entries": []})

    state = build_operator_state(tmp_path, "NovelGen")

    assert state["project"]["status"] == "needs_operator_state_inputs"
    assert state["project_brain"]["healthy"] is False
    assert "next_actions.yml" in state["project_brain"]["missing_files"]
    assert "project_fact_snapshot.yml" in state["project_brain"]["missing_files"]


def test_operator_action_contract_blocks_unsafe_or_unauthored_mutations() -> None:
    missing_auth = validate_operator_action(
        {
            "action": "approve",
            "target_type": "phase_acceptance",
            "target_id": "phase_1_foundation",
        }
    )
    assert missing_auth["status"] == "blocked"
    assert "actor_required" in missing_auth["errors"]
    assert "reason_required" in missing_auth["errors"]

    unsafe = validate_operator_action(
        {
            "action": "retry",
            "target_type": "task",
            "actor": "operator",
            "reason": "retry after missing evidence supplied",
            "requested_effects": ["phase_acceptance_bypass"],
        }
    )
    assert unsafe["status"] == "blocked"
    assert "forbidden_effect:phase_acceptance_bypass" in unsafe["errors"]

    read_only = validate_operator_action({"action": "inspect_evidence", "target_type": "phase"})
    assert read_only["status"] == "ok"
    assert read_only["mutates_state"] is False


def test_operator_action_catalog_lists_forbidden_effects() -> None:
    catalog = build_operator_action_catalog()
    assert "approve" in catalog["actions"]
    assert catalog["actions"]["approve"]["requires_actor"] is True
    assert "direct_production_content_write" in catalog["global_forbidden_effects"]
    assert "external_executor_enablement" in catalog["global_forbidden_effects"]


def test_ops_console_exposes_normalized_operator_state(tmp_path: Path) -> None:
    _project(tmp_path, "Crown_of_Ash")

    snapshot = build_ops_console_snapshot(tmp_path, "Crown_of_Ash")

    assert snapshot["operator_state"]["stage"] == "M3_OPERATOR_OS"
    assert snapshot["operator_state"]["next_action"]["data"]["next_phase_id"] == "phase_2_draft_batch"
    assert snapshot["operator_actions"]["actions"]["reject"]["runtime_contract"]
