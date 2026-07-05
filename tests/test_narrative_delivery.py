from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.cli.governance import apply_migration_proposal, propose_migration
from agent_runtime.narrative_delivery import (
    build_chapter_packet,
    run_narrative_doctor,
    validate_narrative_delivery,
    write_chapter_packet,
)
from agent_runtime.pipeline_runner import _apply_archive_steward_if_needed


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _copy_config_root(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    (root / "config").mkdir(parents=True)
    for name in [
        "content_project_governance.yml",
        "agent_role_bindings.yml",
        "frontdesk_policy.yml",
    ]:
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    return root


def _make_crown_project(root: Path, project: str = "Crown_of_Ash") -> Path:
    project_root = root / "projects" / project
    (project_root / "production" / "bible").mkdir(parents=True)
    (project_root / "production" / "outlines").mkdir(parents=True)
    (project_root / "production" / "manuscript").mkdir(parents=True)
    (project_root / "production" / "bible" / "角色圣经.md").write_text("# Roles\n", encoding="utf-8")
    (project_root / "production" / "outlines" / "02_卷纲与章节路线.md").write_text("# Outline\n", encoding="utf-8")
    (project_root / "production" / "manuscript" / "第01章_灰谷镇的灰.md").write_text("# Ch1\n", encoding="utf-8")
    _write_yaml(
        project_root / "project_artifact_index.yml",
        {
            "artifacts": [
                {"artifact_id": "manuscript_series", "status": "current", "production_path": "production/manuscript/"},
                {"artifact_id": "project_bible", "status": "current", "production_path": "production/bible/"},
                {"artifact_id": "outline_set", "status": "current", "production_path": "production/outlines/"},
            ]
        },
    )
    brain = project_root / "project_brain"
    _write_yaml(brain / "project_fact_snapshot.yml", {"project": project, "event_count": 0})
    (brain / "project_fact_events.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (brain / "project_fact_events.jsonl").write_text("", encoding="utf-8")
    return project_root


def test_prepare_chapter_packet_uses_current_story_sources(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)

    packet = build_chapter_packet(root, "Crown_of_Ash", "task_ch02", 2)
    written = write_chapter_packet(root, "Crown_of_Ash", "task_ch02", 2)

    assert packet["chapter"] == 2
    assert "project_brain/project_fact_snapshot.yml" in packet["must_read"]
    assert "project_artifact_index.yml" in packet["must_read"]
    assert packet["previous_chapters"] == ["production/manuscript/第01章_灰谷镇的灰.md"]
    assert {"fiction_draft.md", "fiction_review.yml", "continuity_ledger.yml"} <= set(packet["required_outputs"])
    assert written["path"] == "projects/Crown_of_Ash/runs/task_ch02/chapter_packet.yml"


def test_narrative_doctor_reports_missing_delivery_protocol(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_ch02"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Write chapter 2 of Crown of Ash.", encoding="utf-8")
    _write_yaml(run_dir / "workflow_plan.yml", {"route": {"route_key": "fiction_chapter_pipeline"}})

    result = run_narrative_doctor(root, "Crown_of_Ash")

    assert result["status"] == "fail"
    assert any(issue["check"] == "chapter_packet_present" for issue in result["issues"])
    assert any(issue["check"] == "narrative_delivery_receipt" for issue in result["issues"])


def test_blocking_fiction_review_blocks_archive_gate(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_ch02"
    run_dir.mkdir(parents=True)
    _write_yaml(run_dir / "workflow_plan.yml", {"route": {"route_key": "fiction_chapter_pipeline"}})
    (run_dir / "fiction_draft.md").write_text("# Draft\n\nScene text.\n", encoding="utf-8")
    _write_yaml(
        run_dir / "fiction_review.yml",
        {
            "verdict": "fail",
            "blocking": True,
            "gates": {
                "continuity": {"status": "fail", "finding": "Contradicts chapter 1."},
                "character_state": {"status": "pass"},
            },
        },
    )

    delivery = validate_narrative_delivery(run_dir)
    archive_issues = _apply_archive_steward_if_needed(root, run_dir, "Crown_of_Ash", "task_ch02", "ARCHIVE")

    assert delivery["valid"] is False
    assert any(issue["check"] == "fiction_review_blocking" for issue in delivery["issues"])
    assert any("Narrative delivery gate failed" in issue for issue in archive_issues)


def test_governance_migration_proposal_is_review_first(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root, "NovelGen")
    run_dir = project_root / "runs" / "task_revision"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("Revise the heroine motive.", encoding="utf-8")

    proposal = propose_migration(root, "NovelGen")
    rejected = apply_migration_proposal(root, proposal["proposal_id"], accept=False)

    assert proposal["status"] == "pending"
    assert proposal["destructive"] is False
    assert not (run_dir / "change_request.yml").exists()
    assert rejected["applied"] is False
    applied = apply_migration_proposal(root, proposal["proposal_id"], accept=True, accepted_by="pytest")

    assert applied["applied"] is True
    assert (run_dir / "change_request.yml").exists()
    assert (run_dir / "state_transition_proposal.yml").exists()
