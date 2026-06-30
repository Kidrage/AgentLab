from __future__ import annotations

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.program_manager.phase_acceptance import accept_phase
from agent_runtime.program_manager.project_brain import build_project_brain
from agent_runtime.program_manager.project_fact_state import load_project_fact_snapshot
from agent_runtime.project_artifact_steward import apply_archive_protocol, validate_project_artifact_governance


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _mission(path: Path) -> Path:
    _write_yaml(
        path,
        {
            "task_id": "crown_long_chain",
            "task_type": "creative_longform",
            "user_goal": "Generate a Crown of Ash epic chronicle with timeline branches and saga arcs.",
            "intent_summary": "Crown_of_Ash long-chain content governance regression",
            "required_capabilities": [{"capability": "local_search"}],
            "risk_flags": ["long_running_project"],
        },
    )
    return path


def test_crown_content_candidate_promotes_with_lineage_and_state_transition(tmp_path: Path) -> None:
    root = tmp_path
    project = "Crown_of_Ash"
    task_id = "crown_batch_001"
    project_root = root / "projects" / project
    run_dir = project_root / "runs" / task_id
    brain_dir = project_root / "project_brain"

    _write_yaml(
        root / "config" / "content_project_governance.yml",
        {
            "active_projects": [project],
            "formal_fact_roots": ["production", "project_brain"],
            "candidate_roots": ["candidates", "runs"],
            "archive_roots": ["archive", "_archive"],
            "legacy_fact_dir_patterns": ["*_rebuild", "v[0-9]*_*", "*legacy*", "archive_v*"],
            "required_content_task_outputs": ["artifact_lineage.yml", "state_transition_proposal.yml"],
        },
    )
    build_project_brain(_mission(root / "mission.yml"), project, brain_dir)

    production_file = project_root / "production" / "manuscript" / "volume_01" / "chapter_001.md"
    production_file.parent.mkdir(parents=True, exist_ok=True)
    production_file.write_text("# Chapter 1\n\nOld canon draft.\n", encoding="utf-8")

    candidate_file = run_dir / "artifacts" / "chapter_001.md"
    candidate_file.parent.mkdir(parents=True, exist_ok=True)
    candidate_file.write_text("# Chapter 1\n\nAccepted Crown batch candidate.\n", encoding="utf-8")
    (run_dir / "user_request.md").write_text("Promote Crown batch chapter 001.\n", encoding="utf-8")

    artifact_intent = {
        "version": 1,
        "project": project,
        "task_id": task_id,
        "candidate_dir": str(run_dir / "artifacts"),
        "production_dir": str(project_root / "production"),
        "archive_dir": str(project_root / "archive"),
        "allowed_write_roots": [str(run_dir / "artifacts")],
        "declared_production_paths": ["production/manuscript/volume_01/chapter_001.md"],
        "allowed_overwrite_paths": ["production/manuscript/volume_01/chapter_001.md"],
        "archive_strategy": "copy_existing_before_replace",
    }
    _write_yaml(
        run_dir / "workflow_plan.yml",
        {
            "project": project,
            "task_id": task_id,
            "artifact_intent": artifact_intent,
        },
    )
    _write_yaml(
        project_root / "project_artifact_index.yml",
        {
            "version": 1,
            "project": project,
            "artifacts": [
                {
                    "artifact_id": "chapter_001",
                    "status": "current",
                    "current_version": "v0",
                    "production_path": "production/manuscript/volume_01/chapter_001.md",
                    "source_task": "bootstrap",
                    "source_run_artifact": "manual_seed/chapter_001.md",
                    "evidence_only": False,
                    "archived_versions": [],
                }
            ],
        },
    )
    _write_yaml(
        run_dir / "artifact_lineage.yml",
        {
            "version": 1,
            "project": project,
            "task_id": task_id,
            "replaced": [
                {
                    "path": "production/manuscript/volume_01/chapter_001.md",
                    "source": "artifacts/chapter_001.md",
                }
            ],
        },
    )
    _write_yaml(
        run_dir / "artifact_promotion_plan.yml",
        {
            "version": 1,
            "project": project,
            "task_id": task_id,
            "archive_dir": str(project_root / "archive"),
            "promotions": [
                {
                    "artifact_id": "chapter_001",
                    "source_run_artifact": "artifacts/chapter_001.md",
                    "production_path": "manuscript/volume_01/chapter_001.md",
                    "action": "replace",
                }
            ],
        },
    )
    _write_yaml(
        run_dir / "state_transition_proposal.yml",
        {
            "state_transition_proposal": {
                "project": project,
                "phase_id": task_id,
                "events": [
                    {
                        "event_type": "create",
                        "target_kind": "entity",
                        "target_type": "timeline_branch",
                        "target_id": "emberfall_primary",
                        "to_status": "active",
                        "facts": {
                            "chapter": "chapter_001",
                            "branch_role": "primary",
                        },
                        "evidence_refs": ["artifacts/chapter_001.md"],
                    }
                ],
            }
        },
    )
    _write_yaml(
        run_dir / "continuity_gate_report.yml",
        {
            "verdict": "PASS",
            "candidate_read_as_canon": False,
            "archive_read_without_explicit_index": False,
        },
    )

    phase_path = run_dir / "phase_plan.yml"
    _write_yaml(
        phase_path,
        {
            "project": project,
            "project_brain_dir": str(brain_dir),
            "phase_id": task_id,
            "goal": "Promote accepted Crown chapter batch",
            "outputs": ["chapter_001", "continuity_gate_report"],
            "evidence_required": [
                "artifact_lineage.yml",
                "state_transition_proposal.yml",
                "continuity_gate_report.yml",
            ],
            "human_decision_points": [],
            "state_contract": {
                "project_brain_dir": str(brain_dir),
                "contract_ref": "project_state_contract.yml",
                "snapshot_ref": "project_fact_snapshot.yml",
                "transition_artifact": "state_transition_proposal.yml",
                "transition_proposal_required": True,
            },
        },
    )

    acceptance = accept_phase(phase_path, run_dir, run_dir / "acceptance")
    receipt = apply_archive_protocol(root, project, task_id)
    issues = validate_project_artifact_governance(root, project, task_id, run_dir)
    snapshot = load_project_fact_snapshot(brain_dir)
    index = yaml.safe_load((project_root / "project_artifact_index.yml").read_text(encoding="utf-8"))

    assert acceptance["accepted"] is True
    assert acceptance["state_transition_status"]["applied"] is True
    assert receipt["status"] == "completed"
    assert production_file.read_text(encoding="utf-8") == "# Chapter 1\n\nAccepted Crown batch candidate.\n"
    assert receipt["promotions_applied"][0]["archive_path"].startswith("archive/chapter_001/")
    assert issues == []
    current = [
        artifact
        for artifact in index["artifacts"]
        if artifact["artifact_id"] == "chapter_001" and artifact["status"] == "current"
    ]
    assert len(current) == 1
    assert current[0]["production_path"] == "production/manuscript/volume_01/chapter_001.md"
    assert current[0]["source_task"] == task_id
    assert snapshot["entities"]["timeline_branch"]["emberfall_primary"]["status"] == "active"
    assert snapshot["entities"]["timeline_branch"]["emberfall_primary"]["facts"]["chapter"] == "chapter_001"
