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
    is_narrative_run,
    run_narrative_doctor,
    validate_narrative_delivery,
    write_chapter_packet,
    write_narrative_delivery_receipt,
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
    assert packet["continuity_source_kind"] == "production_manuscript"
    assert "project_brain/project_fact_snapshot.yml" in packet["must_read"]
    assert "project_artifact_index.yml" in packet["must_read"]
    assert packet["previous_chapters"] == ["production/manuscript/第01章_灰谷镇的灰.md"]
    assert {
        "fiction_draft.md",
        "continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_delivery_receipt.yml",
    } <= set(packet["required_outputs"])
    assert "fiction_review.yml" not in packet["required_outputs"]
    assert written["path"] == "projects/Crown_of_Ash/runs/task_ch02/chapter_packet.yml"


def test_early_chapter_packet_uses_core_and_volume_one_outlines(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    outlines = project_root / "production" / "outlines"
    (outlines / "00_重构总纲.md").write_text("# Reset Plan\n", encoding="utf-8")
    (outlines / "01_完整故事蓝图.md").write_text("# Story Blueprint\n", encoding="utf-8")
    (outlines / "世界观设定.md").write_text("# World\n", encoding="utf-8")
    (outlines / "卷纲_第一卷.md").write_text("# Volume One\n", encoding="utf-8")
    (outlines / "卷纲_第二卷.md").write_text("# Volume Two\n", encoding="utf-8")
    (outlines / "卷纲_第三卷.md").write_text("# Volume Three\n", encoding="utf-8")
    (outlines / "04_续作钩子与未完结属性.md").write_text("# Future Hooks\n", encoding="utf-8")

    packet = build_chapter_packet(root, "Crown_of_Ash", "task_ch01", 1)

    outline_refs = packet["story_authority"]["outline_refs"]
    assert "production/outlines/卷纲_第一卷.md" in outline_refs
    assert "production/outlines/卷纲_第二卷.md" not in outline_refs
    assert "production/outlines/卷纲_第三卷.md" not in outline_refs
    assert "production/outlines/04_续作钩子与未完结属性.md" not in outline_refs


def test_candidate_chapter_packet_builds_intent_from_authoritative_route(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    route = project_root / "production" / "outlines" / "02_卷纲与章节路线.md"
    route.write_text(
        """# Route

## 第一卷

### 11-15 章：追捕与裂痕

- 莉亚先纠错，不提供廉价外挂。
- 凯恩发现教团也会牺牲无辜。
""",
        encoding="utf-8",
    )
    previous = [
        "runs/task_ch11/fiction_draft.md",
        "runs/task_ch11/continuity_ledger.yml",
        "runs/task_ch11/state_transition_proposal.yml",
    ]

    packet = build_chapter_packet(
        root,
        "Crown_of_Ash",
        "task_ch12",
        12,
        baseline_mode="continuation",
        previous_chapters=previous,
    )

    assert packet["baseline_mode"] == "continuation"
    assert packet["continuity_source_kind"] == "candidate_run"
    assert packet["previous_candidate_sources"] == previous
    assert not any(source.startswith("production/manuscript/") for source in packet["previous_chapters"])
    intent = packet["chapter_intent"]
    assert intent["source"] == "production/outlines/02_卷纲与章节路线.md"
    assert intent["source_kind"] == "chapter_range_phase"
    assert intent["phase_range"] == [11, 15]
    assert intent["phase_position"]["index"] == 2
    assert intent["beat_plan"]["required_chapter_beat"]
    assert intent["foreshadowing_to_introduce_or_payoff"] in {
        "introduce",
        "touch",
        "escalate",
        "touch_or_reframe",
        "payoff_or_explicitly_defer",
    }


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


def test_code_workflow_with_chinese_modify_prompt_is_not_narrative(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "task_code"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text(
        "请设计并实现 AgentLab 的网页端 UI，允许修改代码，不要修改 production。",
        encoding="utf-8",
    )
    _write_yaml(
        run_dir / "workflow_plan.yml",
        {
            "route": {
                "route_key": "interface_sensitive_task",
                "agents": ["Supervisor", "RepoScout", "InterfaceMapper", "Coder", "TesterAuditor"],
            },
            "production_pack": {"pack_id": "code_factory"},
        },
    )

    assert is_narrative_run(run_dir) is False
    assert validate_narrative_delivery(run_dir)["skipped"] is True


def test_light_chapter_delivery_requires_receipt_for_external_validation(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_ch02"
    run_dir.mkdir(parents=True)
    _write_yaml(run_dir / "workflow_plan.yml", {"route": {"route_key": "narrative_light_chapter"}})
    (run_dir / "chapter_packet.yml").write_text("chapter: 2\n", encoding="utf-8")
    (run_dir / "fiction_draft.md").write_text("# Draft\n\nScene text.\n", encoding="utf-8")
    _write_yaml(run_dir / "continuity_ledger.yml", {"chapter": 2})
    _write_yaml(run_dir / "state_transition_proposal.yml", {"status": "candidate"})

    delivery = validate_narrative_delivery(run_dir)

    assert delivery["valid"] is False
    assert "narrative_delivery_receipt.yml" in delivery["required_files"]
    assert any(issue["file"] == "narrative_delivery_receipt.yml" for issue in delivery["issues"])


def test_write_narrative_receipt_uses_preflight_then_external_validation_requires_receipt(
    tmp_path: Path,
) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_ch02"
    run_dir.mkdir(parents=True)
    _write_yaml(run_dir / "workflow_plan.yml", {"route": {"route_key": "narrative_light_chapter"}})
    (run_dir / "chapter_packet.yml").write_text("chapter: 2\n", encoding="utf-8")
    (run_dir / "fiction_draft.md").write_text("# Draft\n\nScene text.\n", encoding="utf-8")
    _write_yaml(run_dir / "continuity_ledger.yml", {"chapter": 2})
    _write_yaml(run_dir / "state_transition_proposal.yml", {"status": "candidate"})

    receipt = write_narrative_delivery_receipt(run_dir)
    delivery = validate_narrative_delivery(run_dir)

    assert receipt["status"] == "pass"
    assert (run_dir / "narrative_delivery_receipt.yml").exists()
    assert delivery["valid"] is True
    assert "narrative_delivery_receipt.yml" not in receipt["preflight_required_files"]
    assert "narrative_delivery_receipt.yml" in receipt["external_required_files"]
    assert "narrative_delivery_receipt.yml" in delivery["required_files"]


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
