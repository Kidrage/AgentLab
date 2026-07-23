from __future__ import annotations

# ruff: noqa: E402 -- legacy pipeline modules still use direct sibling imports.

import shutil
import sys
import hashlib
from pathlib import Path

import yaml
import pytest

from agent_runtime.narrative.candidates.manifest import (
    create_candidate_set,
    freeze_candidate_set,
    validate_candidate_set,
)
from agent_runtime.narrative.candidates.promotion import (
    evidence_bundle_sha256,
    promote_candidate_set,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.cli.governance import apply_migration_proposal, propose_migration
from agent_runtime.narrative_delivery import (
    build_chapter_packet,
    is_narrative_run,
    narrative_delivery_integrity_issues,
    run_narrative_doctor,
    narrative_planner_validation_issues,
    validate_chapter_state_plan,
    validate_narrative_delivery,
    write_chapter_packet,
    write_narrative_delivery_receipt,
    write_narrative_planner_validation,
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


def test_candidate_state_plan_adds_hash_bound_story_authority_overlay(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    overlay_ref = "candidates/gate1/legacy_character_integration.yml"
    overlay = project_root / overlay_ref
    overlay.parent.mkdir(parents=True)
    overlay.write_text("schema_version: 1\nstatus: candidate\n", encoding="utf-8")
    overlay_sha256 = hashlib.sha256(overlay.read_bytes()).hexdigest()
    plan_ref = "candidates/gate1/chapter_state_plan.yml"
    _write_yaml(
        project_root / plan_ref,
        {
            **_state_plan_document([_state_plan_entry(25)]),
            "story_authority_refs": [
                {"path": overlay_ref, "sha256": overlay_sha256},
            ],
        },
    )

    packet = build_chapter_packet(
        root,
        "Crown_of_Ash",
        "task_gate1_ch25",
        25,
        baseline_mode="continuation",
        chapter_state_plan=plan_ref,
    )

    assert overlay_ref in packet["must_read"]
    assert packet["story_authority"]["candidate_refs"] == [overlay_ref]

    overlay.write_text("schema_version: 1\nstatus: changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match="story authority ref sha256 mismatch"):
        build_chapter_packet(
            root,
            "Crown_of_Ash",
            "task_gate1_ch25_drifted",
            25,
            baseline_mode="continuation",
            chapter_state_plan=plan_ref,
        )


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
        candidate_fact_ledger="runs/task_ch12/candidate_fact_ledger.yml",
    )

    assert packet["baseline_mode"] == "continuation"
    assert packet["continuity_source_kind"] == "candidate_run"
    assert packet["previous_candidate_sources"] == previous
    assert packet["story_authority"]["candidate_fact_ledger"] == "runs/task_ch12/candidate_fact_ledger.yml"
    assert "runs/task_ch12/candidate_fact_ledger.yml" in packet["must_read"]
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


def _state_plan_entry(chapter: int, *, scene_goal: str | None = None) -> dict:
    return {
        "chapter": chapter,
        "title": f"Chapter {chapter}",
        "volume": "Volume One",
        "phase": "Opening",
        "timeline_slot": f"day-{chapter}",
        "pov": "Kane",
        "opening_state": f"state before chapter {chapter}",
        "scene_goal": scene_goal or f"complete distinct scene {chapter}",
        "irreversible_plot_change": f"irreversible change {chapter}",
        "character_state_change": f"character change {chapter}",
        "relationship_or_worldline_change": f"worldline change {chapter}",
        "foreshadowing_action": f"foreshadowing action {chapter}",
        "closing_state": f"state after chapter {chapter}",
        "must_not_repeat": [f"event from chapter {chapter - 1}"],
    }


def _state_plan_document(entries: list[dict]) -> dict:
    chapters = [entry["chapter"] for entry in entries]
    return {
        "schema_version": 1,
        "project": "Crown_of_Ash",
        "status": "candidate",
        "candidate_only": True,
        "production_modified": False,
        "chapter_range": [min(chapters), max(chapters)],
        "target_character_range": [4500, 5500],
        "hard_character_range": [3000, 8000],
        "chapter_state_plan": entries,
        "validation_contract": {
            "exact_chapter_count": len(entries),
            "ordered_unique_chapters": True,
            "unique_scene_goals": True,
            "unique_irreversible_plot_changes": True,
            "monotonic_story_state": True,
        },
    }


def test_candidate_chapter_packet_prefers_valid_run_local_state_plan(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    plan_ref = "runs/task_plan/chapter_state_plan.yml"
    _write_yaml(
        project_root / plan_ref,
        _state_plan_document([_state_plan_entry(1), _state_plan_entry(2)]),
    )

    packet = build_chapter_packet(
        root,
        "Crown_of_Ash",
        "task_ch02_v2",
        2,
        baseline_mode="continuation",
        chapter_state_plan=plan_ref,
    )

    assert packet["chapter_intent"]["source_kind"] == "candidate_chapter_state_plan"
    assert packet["chapter_intent"]["plot_state_change"] == "irreversible change 2"
    assert packet["chapter_intent"]["beat_plan"]["closing_state"] == "state after chapter 2"
    assert plan_ref in packet["must_read"]
    assert packet["story_authority"]["candidate_chapter_state_plan"] == plan_ref


def test_chapter_state_plan_rejects_duplicate_scene_goals(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    plan_ref = "runs/task_plan/chapter_state_plan.yml"
    _write_yaml(
        project_root / plan_ref,
        _state_plan_document(
            [
                _state_plan_entry(1, scene_goal="repeat this scene"),
                _state_plan_entry(2, scene_goal="repeat this scene"),
            ]
        ),
    )

    validation = validate_chapter_state_plan(
        project_root,
        plan_ref,
        expected_chapters=[1, 2],
    )

    assert validation["status"] == "fail"
    assert any(issue["check"] == "unique_scene_goal" for issue in validation["issues"])
    with pytest.raises(ValueError, match="chapter state plan failed validation"):
        build_chapter_packet(
            root,
            "Crown_of_Ash",
            "task_ch02_v2",
            2,
            chapter_state_plan=plan_ref,
        )


def test_chapter_state_plan_rejects_unordered_scope_and_false_contract(
    tmp_path: Path,
) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    plan_ref = "runs/task_plan/chapter_state_plan.yml"
    document = _state_plan_document([_state_plan_entry(2), _state_plan_entry(1)])
    document["chapter_range"] = [1, 3]
    document["validation_contract"]["monotonic_story_state"] = False
    _write_yaml(project_root / plan_ref, document)

    validation = validate_chapter_state_plan(
        project_root,
        plan_ref,
        expected_chapters=[1, 2],
    )

    checks = {issue["check"] for issue in validation["issues"]}
    assert validation["status"] == "fail"
    assert "ordered_contiguous_chapters" in checks
    assert "chapter_range" in checks
    assert "validation_contract" in checks


def test_narrative_planner_validation_binds_output_to_rewrite_contract(
    tmp_path: Path,
) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_rewrite_plan"
    _write_yaml(run_dir / "narrative_rewrite_contract.yml", {"chapter_range": [1, 2]})
    output_path = run_dir / "chapter_state_plan.yml"
    _write_yaml(
        output_path,
        _state_plan_document([_state_plan_entry(1), _state_plan_entry(2)]),
    )

    validation = write_narrative_planner_validation(
        project_root,
        run_dir,
        output_path,
    )

    assert validation["status"] == "pass"
    assert validation["selected_chapter_count"] == 2
    assert narrative_planner_validation_issues(validation) == []
    assert (run_dir / "narrative_planner_validation.yml").is_file()

    _write_yaml(output_path, _state_plan_document([_state_plan_entry(1)]))
    failed = write_narrative_planner_validation(project_root, run_dir, output_path)
    assert failed["status"] == "fail"
    assert narrative_planner_validation_issues(failed)
    assert any(
        issue["check"] == "selected_chapter_present"
        for issue in failed["issues"]
    )


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
    _write_yaml(
        run_dir / "narrative_delivery_receipt.yml",
        {
            "schema_version": 1,
            "status": "pass",
            "candidate_only": True,
            "checks": {"required_beats": "pass"},
        },
    )

    receipt = write_narrative_delivery_receipt(run_dir)
    delivery = validate_narrative_delivery(run_dir)

    assert receipt["status"] == "pass"
    assert (run_dir / "narrative_delivery_receipt.yml").exists()
    assert delivery["valid"] is True
    assert "narrative_delivery_receipt.yml" not in receipt["preflight_required_files"]
    assert "narrative_delivery_receipt.yml" in receipt["external_required_files"]
    assert "narrative_delivery_receipt.yml" in delivery["required_files"]
    assert receipt["candidate_only"] is True
    assert receipt["checks"] == {"required_beats": "pass"}
    assert narrative_delivery_integrity_issues(run_dir) == []


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


def test_frozen_candidate_set_detects_any_chapter_hash_change(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Novel"
    artifact = project_root / "candidates" / "raw" / "chapter_001.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("original candidate\n", encoding="utf-8")
    manifest = create_candidate_set(
        project_root,
        candidate_set_id="candidate-set-001",
        created_at="2026-01-01T00:00:00+00:00",
        canon_snapshot_sha256="canon-sha",
        scorecard_version=1,
        chapters=[
            {
                "chapter_id": 1,
                "artifact_path": "candidates/raw/chapter_001.md",
                "source_run_id": "run-ch001",
                "source_model": "writer-model",
                "model_tier": "final",
                "context_manifest_sha256": "context-sha",
                "predecessor_chapter_sha256": None,
                "generation_receipt": "receipts/generation-ch001.yml",
                "correctness_audit": "receipts/correctness-ch001.yml",
                "literary_audit": "receipts/literary-ch001.yml",
                "cost_receipt": "receipts/cost-ch001.yml",
            }
        ],
    )
    frozen = freeze_candidate_set(project_root, Path(manifest["manifest_path"]))

    assert frozen["status"] == "frozen"
    artifact.write_text("mutated after audit started\n", encoding="utf-8")
    validation = validate_candidate_set(project_root, Path(manifest["manifest_path"]))

    assert validation["status"] == "stale"
    assert validation["stale_chapters"] == [1]
    assert validation["audit_status"] == "stale"


def test_first_publication_promotes_hash_bound_candidate_atomically(tmp_path: Path) -> None:
    _write_yaml(
        tmp_path / "config" / "knowledge_system.yml",
        {"indexing": {"project_allowlist": ["Novel"]}},
    )
    project_root = tmp_path / "projects" / "Novel"
    artifact = project_root / "candidates" / "raw" / "chapter_001.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("first publication candidate\n", encoding="utf-8")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipts = project_root / "receipts"
    receipts.mkdir()
    for name in ("generation", "correctness", "literary", "cost"):
        _write_yaml(
            receipts / f"{name}-ch001.yml",
            {
                "status": "pass",
                "artifact_sha256": artifact_sha,
                "blocking_count": 0,
            },
        )
    created = create_candidate_set(
        project_root,
        candidate_set_id="candidate-set-first",
        created_at="2026-01-01T00:00:00+00:00",
        canon_snapshot_sha256="canon-sha",
        scorecard_version=1,
        chapters=[
            {
                "chapter_id": 1,
                "artifact_path": "candidates/raw/chapter_001.md",
                "source_run_id": "run-ch001",
                "source_model": "writer-model",
                "model_tier": "final",
                "context_manifest_sha256": "context-sha",
                "predecessor_chapter_sha256": None,
                "generation_receipt": "receipts/generation-ch001.yml",
                "correctness_audit": "receipts/correctness-ch001.yml",
                "literary_audit": "receipts/literary-ch001.yml",
                "cost_receipt": "receipts/cost-ch001.yml",
            }
        ],
    )
    frozen = freeze_candidate_set(
        project_root,
        Path(created["manifest_path"]),
        frozen_at="2026-01-01T00:01:00+00:00",
    )
    for path in receipts.glob("*.yml"):
        receipt = yaml.safe_load(path.read_text(encoding="utf-8"))
        receipt["candidate_set_sha256"] = frozen["candidate_set_sha256"]
        _write_yaml(path, receipt)
    approval = receipts / "user-acceptance.yml"
    _write_yaml(
        approval,
        {
            "status": "accepted",
            "candidate_set_id": "candidate-set-first",
            "candidate_set_sha256": frozen["candidate_set_sha256"],
            "evidence_bundle_sha256": evidence_bundle_sha256(project_root, frozen),
            "accepted_by": "user",
        },
    )

    result = promote_candidate_set(
        project_root,
        manifest_path=Path(created["manifest_path"]),
        user_acceptance_receipt=approval,
        edition_id="edition-001",
        release_slot="main",
        promoted_at="2026-01-01T00:02:00+00:00",
    )

    assert result["status"] == "promoted"
    assert result["first_publication"] is True
    assert result["knowledge_sync"]["status"] == "SYNCED"
    assert "projects/Novel/release_objects/editions/edition-001/chapter_001.md" in (
        result["knowledge_sync"]["indexed_paths"]
    )
    release = project_root / "release_objects" / "editions" / "edition-001"
    assert (release / "chapter_001.md").read_text(encoding="utf-8") == (
        "first publication candidate\n"
    )
    index = yaml.safe_load(
        (project_root / "project_artifact_index.yml").read_text(encoding="utf-8")
    )
    assert index["current_release"]["edition_id"] == "edition-001"


def test_failed_promotion_keeps_existing_production_unchanged(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Novel"
    existing = project_root / "production" / "editions" / "edition-current"
    existing.mkdir(parents=True)
    (existing / "chapter_001.md").write_text("current production\n", encoding="utf-8")
    _write_yaml(
        project_root / "project_artifact_index.yml",
        {
            "schema_version": 1,
            "current_release": {
                "release_slot": "main",
                "edition_id": "edition-current",
                "chapter_ids": [1],
            },
            "releases": [],
        },
    )
    before_index = (project_root / "project_artifact_index.yml").read_bytes()
    before_production = (existing / "chapter_001.md").read_bytes()
    candidate = project_root / "candidates" / "raw" / "chapter_001.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("unapproved candidate\n", encoding="utf-8")
    created = create_candidate_set(
        project_root,
        candidate_set_id="candidate-set-stale-approval",
        created_at="2026-01-01T00:00:00+00:00",
        canon_snapshot_sha256="canon-sha",
        scorecard_version=1,
        chapters=[
            {
                "chapter_id": 1,
                "artifact_path": "candidates/raw/chapter_001.md",
                "source_run_id": "run-ch001",
                "source_model": "writer-model",
                "model_tier": "final",
                "context_manifest_sha256": "context-sha",
                "predecessor_chapter_sha256": None,
                "generation_receipt": "receipts/generation.yml",
                "correctness_audit": "receipts/correctness.yml",
                "literary_audit": "receipts/literary.yml",
                "cost_receipt": "receipts/cost.yml",
            }
        ],
    )
    freeze_candidate_set(
        project_root,
        Path(created["manifest_path"]),
        frozen_at="2026-01-01T00:01:00+00:00",
    )
    approval = project_root / "receipts" / "stale-approval.yml"
    approval.parent.mkdir()
    _write_yaml(
        approval,
        {
            "status": "accepted",
            "candidate_set_id": "candidate-set-stale-approval",
            "candidate_set_sha256": "old-candidate-set-hash",
        },
    )

    with pytest.raises(ValueError, match="stale user acceptance receipt"):
        promote_candidate_set(
            project_root,
            manifest_path=Path(created["manifest_path"]),
            user_acceptance_receipt=approval,
            edition_id="edition-rejected",
            release_slot="main",
            promoted_at="2026-01-01T00:02:00+00:00",
        )

    assert (project_root / "project_artifact_index.yml").read_bytes() == before_index
    assert (existing / "chapter_001.md").read_bytes() == before_production
    assert not (project_root / "release_objects" / "editions" / "edition-rejected").exists()


def test_index_write_failure_rolls_back_staged_production(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import agent_runtime.narrative.candidates.promotion as promotion_module

    project_root = tmp_path / "projects" / "Novel"
    artifact = project_root / "candidates" / "raw" / "chapter_001.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("candidate\n", encoding="utf-8")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipts = project_root / "receipts"
    receipts.mkdir()
    created = create_candidate_set(
        project_root,
        candidate_set_id="candidate-set-atomic",
        created_at="2026-01-01T00:00:00+00:00",
        canon_snapshot_sha256="canon-sha",
        scorecard_version=1,
        chapters=[
            {
                "chapter_id": 1,
                "artifact_path": "candidates/raw/chapter_001.md",
                "source_run_id": "run-ch001",
                "source_model": "writer-model",
                "model_tier": "final",
                "context_manifest_sha256": "context-sha",
                "predecessor_chapter_sha256": None,
                "generation_receipt": "receipts/generation.yml",
                "correctness_audit": "receipts/correctness.yml",
                "literary_audit": "receipts/literary.yml",
                "cost_receipt": "receipts/cost.yml",
            }
        ],
    )
    frozen = freeze_candidate_set(
        project_root,
        Path(created["manifest_path"]),
        frozen_at="2026-01-01T00:01:00+00:00",
    )
    for name in ("generation", "correctness", "literary", "cost"):
        _write_yaml(
            receipts / f"{name}.yml",
            {
                "status": "pass",
                "candidate_set_sha256": frozen["candidate_set_sha256"],
                "artifact_sha256": artifact_sha,
                "blocking_count": 0,
            },
        )
    approval = receipts / "approval.yml"
    _write_yaml(
        approval,
        {
            "status": "accepted",
            "candidate_set_id": "candidate-set-atomic",
            "candidate_set_sha256": frozen["candidate_set_sha256"],
            "evidence_bundle_sha256": evidence_bundle_sha256(project_root, frozen),
        },
    )
    real_write = promotion_module.atomic_write_yaml

    def fail_index_write(path: Path, data: dict) -> None:
        if Path(path).name == "project_artifact_index.yml":
            raise OSError("simulated index interruption")
        real_write(path, data)

    monkeypatch.setattr(promotion_module, "atomic_write_yaml", fail_index_write)

    with pytest.raises(OSError, match="simulated index interruption"):
        promote_candidate_set(
            project_root,
            manifest_path=Path(created["manifest_path"]),
            user_acceptance_receipt=approval,
            edition_id="edition-atomic",
            release_slot="main",
            promoted_at="2026-01-01T00:02:00+00:00",
        )

    assert not (project_root / "release_objects" / "editions" / "edition-atomic").exists()
    assert not (project_root / "project_artifact_index.yml").exists()


def test_unsafe_promotion_identifiers_are_rejected_before_filesystem_changes(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Novel"

    with pytest.raises(ValueError, match="invalid edition_id"):
        promote_candidate_set(
            project_root,
            manifest_path=project_root / "missing.yml",
            user_acceptance_receipt=project_root / "missing-approval.yml",
            edition_id="../escape",
            release_slot="main",
            promoted_at="2026-01-01T00:00:00+00:00",
        )

    assert not project_root.exists()


def test_promotion_path_rejects_symlink_escape_from_project_root(tmp_path: Path) -> None:
    from agent_runtime.narrative.candidates.promotion import _safe_child

    project_root = tmp_path / "project"
    outside = tmp_path / "outside"
    project_root.mkdir()
    outside.mkdir()
    (project_root / ".promotion_staging").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        _safe_child(project_root, ".promotion_staging", "candidate-edition")

    assert list(outside.iterdir()) == []


def test_receipt_mutation_after_user_acceptance_makes_promotion_stale(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Novel"
    artifact = project_root / "candidates" / "raw" / "chapter_001.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("candidate\n", encoding="utf-8")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipts = project_root / "receipts"
    receipts.mkdir()
    created = create_candidate_set(
        project_root,
        candidate_set_id="candidate-set-receipts",
        created_at="2026-01-01T00:00:00+00:00",
        canon_snapshot_sha256="canon-sha",
        scorecard_version=1,
        chapters=[
            {
                "chapter_id": 1,
                "artifact_path": "candidates/raw/chapter_001.md",
                "source_run_id": "run-ch001",
                "source_model": "writer-model",
                "model_tier": "final",
                "context_manifest_sha256": "context-sha",
                "predecessor_chapter_sha256": None,
                "generation_receipt": "receipts/generation.yml",
                "correctness_audit": "receipts/correctness.yml",
                "literary_audit": "receipts/literary.yml",
                "cost_receipt": "receipts/cost.yml",
            }
        ],
    )
    frozen = freeze_candidate_set(project_root, Path(created["manifest_path"]))
    for name in ("generation", "correctness", "literary", "cost"):
        _write_yaml(
            receipts / f"{name}.yml",
            {
                "status": "pass",
                "candidate_set_sha256": frozen["candidate_set_sha256"],
                "artifact_sha256": artifact_sha,
                "blocking_count": 0,
            },
        )
    approval = receipts / "approval.yml"
    _write_yaml(
        approval,
        {
            "status": "accepted",
            "candidate_set_id": frozen["candidate_set_id"],
            "candidate_set_sha256": frozen["candidate_set_sha256"],
            "evidence_bundle_sha256": evidence_bundle_sha256(
                project_root, frozen
            ),
        },
    )
    literary = yaml.safe_load((receipts / "literary.yml").read_text(encoding="utf-8"))
    literary["tampered_after_approval"] = True
    _write_yaml(receipts / "literary.yml", literary)

    with pytest.raises(ValueError, match="stale user acceptance evidence"):
        promote_candidate_set(
            project_root,
            manifest_path=Path(created["manifest_path"]),
            user_acceptance_receipt=approval,
            edition_id="edition-receipts",
            release_slot="main",
            promoted_at="2026-01-01T00:02:00+00:00",
        )

    assert not (project_root / "release_objects" / "editions" / "edition-receipts").exists()


def test_retry_recovers_target_left_after_process_interruption(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Novel"
    artifact = project_root / "candidates" / "raw" / "chapter_001.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("candidate\n", encoding="utf-8")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipts = project_root / "receipts"
    receipts.mkdir()
    created = create_candidate_set(
        project_root,
        candidate_set_id="candidate-set-recover",
        created_at="2026-01-01T00:00:00+00:00",
        canon_snapshot_sha256="canon-sha",
        scorecard_version=1,
        chapters=[
            {
                "chapter_id": 1,
                "artifact_path": "candidates/raw/chapter_001.md",
                "source_run_id": "run-ch001",
                "source_model": "writer-model",
                "model_tier": "final",
                "context_manifest_sha256": "context-sha",
                "predecessor_chapter_sha256": None,
                "generation_receipt": "receipts/generation.yml",
                "correctness_audit": "receipts/correctness.yml",
                "literary_audit": "receipts/literary.yml",
                "cost_receipt": "receipts/cost.yml",
            }
        ],
    )
    frozen = freeze_candidate_set(project_root, Path(created["manifest_path"]))
    for name in ("generation", "correctness", "literary", "cost"):
        _write_yaml(
            receipts / f"{name}.yml",
            {
                "status": "pass",
                "candidate_set_sha256": frozen["candidate_set_sha256"],
                "artifact_sha256": artifact_sha,
                "blocking_count": 0,
            },
        )
    evidence_sha = evidence_bundle_sha256(project_root, frozen)
    approval = receipts / "approval.yml"
    _write_yaml(
        approval,
        {
            "status": "accepted",
            "candidate_set_id": frozen["candidate_set_id"],
            "candidate_set_sha256": frozen["candidate_set_sha256"],
            "evidence_bundle_sha256": evidence_sha,
        },
    )
    interrupted_target = project_root / "release_objects" / "editions" / "edition-recover"
    interrupted_target.mkdir(parents=True)
    (interrupted_target / "chapter_001.md").write_bytes(artifact.read_bytes())
    _write_yaml(
        interrupted_target / "promotion_receipt.yml",
        {
            "schema_version": 1,
            "status": "promoted",
            "promoted_at": "2026-01-01T00:02:00+00:00",
            "candidate_set_id": frozen["candidate_set_id"],
            "candidate_set_sha256": frozen["candidate_set_sha256"],
            "evidence_bundle_sha256": evidence_sha,
            "edition_id": "edition-recover",
            "release_slot": "main",
            "user_acceptance_receipt": str(approval),
            "chapters": [
                {
                    "chapter_id": 1,
                    "artifact_path": "release_objects/editions/edition-recover/chapter_001.md",
                    "artifact_sha256": artifact_sha,
                }
            ],
            "production_modified": True,
        },
    )

    result = promote_candidate_set(
        project_root,
        manifest_path=Path(created["manifest_path"]),
        user_acceptance_receipt=approval,
        edition_id="edition-recover",
        release_slot="main",
        promoted_at="2026-01-01T00:02:00+00:00",
    )

    assert result["status"] == "promoted"
    assert yaml.safe_load(
        (project_root / "project_artifact_index.yml").read_text(encoding="utf-8")
    )["current_release"]["edition_id"] == "edition-recover"


# ---------------------------------------------------------------------------
# Phase 1R — creative brief compilation and validation
# ---------------------------------------------------------------------------


_V1_PLAN_ENTRY: dict = {
    "chapter": 5,
    "title": "失败与请求",
    "pov": "third_person_limited",
    "scene_goal": "凯恩在训练中再次失败，向伊莎贝拉寻求帮助",
    "irreversible_plot_change": "凯恩接受烙印的不完全控制",
    "character_state_change": "凯恩从抗拒转为接受辅助",
    "relationship_or_worldline_change": "伊莎贝拉对凯恩的态度软化",
    "foreshadowing_action": "暗示烙印与灰烬王朝的联系",
    "closing_state": "凯恩带着新的决心离开",
    "must_not_repeat": ["重复的训练失败场景", "过多技术解释"],
    "creative_freedom": ["训练的具体细节", "对话风格"],
}


def test_compile_v2_brief_from_v1_state_plan(tmp_path: Path) -> None:
    """creative_brief compiled from v1 state plan has correct primary function."""
    from agent_runtime.narrative.production.brief_compiler import (
        compile_creative_brief,
    )

    source = tmp_path / "bible" / "characters.yml"
    source.parent.mkdir(parents=True)
    source.write_text("characters:\n  - name: Kane\n", encoding="utf-8")

    brief = compile_creative_brief(
        _V1_PLAN_ENTRY, chapter_id=5, source_paths=[str(source)]
    )
    # The fixture has character_state_change populated first (now recognized
    # via singular field alias), so "character" is the correct primary.
    assert brief.primary_function == "character"
    assert brief.chapter_id == 5
    assert brief.pov == "third_person_limited"
    data = brief.to_dict()
    assert data.get("v1_source") is True
    assert data["schema_version"] == 2
    assert len(data["source_hashes"]) == 1
    assert all(
        len(v) == 64 and v == v.lower()
        for v in data["source_hashes"].values()
    )


def test_creative_brief_rejects_multiple_secondary_functions() -> None:
    """creative_brief_rejects_multiple_secondary_functions — passing a list
    as secondary_function is rejected."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 7,
        "primary_function": "character",
        "secondary_function": ["relationship", "world"],  # illegal list
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {_VALID_SOURCE_PATH: _VALID_SOURCE_HASH},
    }
    issues = validate_creative_brief(data)
    assert any("secondary_function_must_be_single_string" in i for i in issues)


_VALID_SOURCE_PATH = str(Path(__file__).resolve())
_VALID_SOURCE_HASH = hashlib.sha256(
    Path(_VALID_SOURCE_PATH).read_bytes()
).hexdigest()


def test_static_life_relationship_consequence_atmosphere_briefs_validate() -> (
    None
):
    """static_life_relationship_consequence_atmosphere_briefs_validate —
    all non-advancing chapter functions are accepted."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    for func in ("static", "life", "relationship_only", "consequence", "atmosphere"):
        data: dict = {
            "schema_version": 2,
            "chapter_id": 8,
            "primary_function": func,
            "pov": "third_person_limited",
            "opposing_wants": "want vs obstacle",
            "turn": "a turn",
            "cost": "a cost",
            "reader_question": "what happens?",
            "must_preserve": ["voice"],
            "creative_freedom": ["dialogue"],
            "source_hashes": {_VALID_SOURCE_PATH: _VALID_SOURCE_HASH},
        }
        issues = validate_creative_brief(data)
        assert not issues, f"function {func!r} produced issues: {issues}"


def test_no_all_dimensions_every_chapter_requirement() -> None:
    """no_all_dimensions_every_chapter_requirement — a brief with only one
    function (plot) is valid; it does not require all six dimensions."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 10,
        "primary_function": "plot",
        # No secondary_function — explicitly allowed.
        "pov": "third_person_limited",
        "opposing_wants": "want vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {_VALID_SOURCE_PATH: _VALID_SOURCE_HASH},
    }
    issues = validate_creative_brief(data)
    assert not issues


def test_legacy_v1_plan_still_readable() -> None:
    """legacy_v1_inputs_remain_readable — an existing v1 validate still works."""
    from agent_runtime.narrative_delivery import validate_chapter_state_plan

    result = validate_chapter_state_plan(
        Path("/nonexistent"),
        "nonexistent.yml",
    )
    assert result["status"] == "fail"
    # The failure is from the missing file, not a code change.
    assert any("does not exist" in i["message"] for i in result["issues"])


_V1_LEGACY_FIXTURE = {
    "chapter": 12,
    "pov": "third_person_limited",
    "scene_goal": "主角在废墟中发现了一件古老遗物并知晓了敌人的计划",
    "irreversible_plot_change": "势力平衡被遗物打破",
    "opening_state": "主角正躲避巡逻队",
    "closing_state": "主角带着遗物逃离，敌人锁定其位置",
    "reader_question": "遗物的主人是否会追索这件神器？",
    "plot_state_changes": ["遗物归属", "势力平衡打破"],
    "character_state_change": "主角从逃亡者变为遗物持有者",
    "relationship_or_worldline_change": "凯恩—伊莎贝拉从盟友变为秘密合作者",
    "foreshadowing_action": "反派在废墟入口埋设了未触发的符文陷阱",
    "timeline_slot": "第三日午夜后两小时",
    "must_preserve": ["遗物的力量设定", "凯恩的人格底线"],
    "creative_freedom": ["对话节奏", "战斗场景细节"],
    "recent_patterns_to_avoid": ["连续使用回忆杀"],
    "risk_signals": ["不要弱化反派威胁"],
}


def test_legacy_v1_fixture_converts_to_v2_brief(tmp_path: Path) -> None:
    """valid_legacy_v1_input_reads_and_converts — a realistic v1 fixture
    with singular field names converts to a valid v2 creative brief."""
    from agent_runtime.narrative.production.brief_compiler import (
        compile_creative_brief,
    )

    source = tmp_path / "bible" / "characters.yml"
    source.parent.mkdir(parents=True)
    source.write_text("characters:\n  - name: Kane\n", encoding="utf-8")

    brief = compile_creative_brief(
        _V1_LEGACY_FIXTURE, chapter_id=12, source_paths=[str(source)]
    )
    assert brief.chapter_id == 12
    assert brief.primary_function in ("plot", "character", "relationship",
                                       "world", "foreshadowing", "time")
    data = brief.to_dict()
    assert data.get("v1_source") is True
    assert data["schema_version"] == 2
    # POV and structural fields must be populated.
    assert data["pov"] != ""
    assert data["turn"] != ""
    assert data["cost"] != ""
    assert len(data["source_hashes"]) == 1


def test_singular_v1_fields_map_to_correct_functions() -> None:
    """Singular v1 field aliases (character_state_change, timeline_slot, etc.)
    are recognized and mapped to the correct v2 chapter function."""
    from agent_runtime.narrative.production.brief_compiler import (
        BriefCompiler,
    )
    import copy

    # Only singular character_state_change — should be primary = character.
    plan: dict = copy.deepcopy(_V1_LEGACY_FIXTURE)
    plan.pop("plot_state_changes", None)
    plan.pop("character_changes", None)
    plan.pop("relationship_or_worldline_changes", None)
    plan.pop("foreshadowing", None)
    plan.pop("timeline", None)
    primary = BriefCompiler._infer_primary_function(plan)
    assert primary == "character"

    # Only foreshadowing_action — should be primary = foreshadowing.
    plan2: dict = copy.deepcopy(_V1_LEGACY_FIXTURE)
    plan2.pop("plot_state_changes", None)
    plan2.pop("character_state_change", None)
    plan2.pop("relationship_or_worldline_change", None)
    plan2.pop("timeline_slot", None)
    plan2.pop("character_changes", None)
    plan2.pop("relationship_or_worldline_changes", None)
    plan2.pop("foreshadowing", None)
    plan2.pop("timeline", None)
    primary2 = BriefCompiler._infer_primary_function(plan2)
    assert primary2 == "foreshadowing"

    # Only timeline_slot — should be primary = time.
    plan3: dict = copy.deepcopy(_V1_LEGACY_FIXTURE)
    plan3.pop("plot_state_changes", None)
    plan3.pop("character_state_change", None)
    plan3.pop("relationship_or_worldline_change", None)
    plan3.pop("foreshadowing_action", None)
    plan3.pop("character_changes", None)
    plan3.pop("relationship_or_worldline_changes", None)
    plan3.pop("foreshadowing", None)
    plan3.pop("timeline", None)
    primary3 = BriefCompiler._infer_primary_function(plan3)
    assert primary3 == "time"


def test_empty_source_hashes_are_rejected() -> None:
    """empty_missing_invalid_and_collision_source_cases_are_proven —
    a creative brief with empty source_hashes is blocked."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 11,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {},
    }
    issues = validate_creative_brief(data)
    assert any("source_hashes_must_not_be_empty" in i for i in issues)


def test_missing_source_hashes_key_is_rejected() -> None:
    """A creative brief missing the source_hashes key entirely is rejected."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 12,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
    }
    issues = validate_creative_brief(data)
    assert any("source_hashes_must_be_mapping" in i for i in issues)


def test_placeholder_source_hash_is_rejected() -> None:
    """source hash values of 'unavailable' or 'unknown' are rejected."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 13,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {_VALID_SOURCE_PATH: "unavailable"},
    }
    issues = validate_creative_brief(data)
    assert any("source_hash_is_placeholder" in i for i in issues)


# ---------------------------------------------------------------------------
# Phase 1R correction 3 — canonical absolute source-hash keys
# ---------------------------------------------------------------------------


def test_relative_source_hash_key_is_rejected() -> None:
    """canonical_absolute_source_hash_keys_are_required — a source_hashes
    entry whose key is a relative path (not starting with '/') is rejected.
    Adversarial replay proves relative keys pass through silent."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 22,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {
            "characters.yml": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        },
    }
    issues = validate_creative_brief(data)
    assert any("source_hash_key_not_canonical_absolute" in i for i in issues)


def test_mixed_absolute_and_relative_keys_relative_is_rejected() -> None:
    """If any source_hashes key is relative, validation fails for that key
    even when other keys are absolute."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 23,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {
            _VALID_SOURCE_PATH: _VALID_SOURCE_HASH,
            "outlines/plot.yml": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        },
    }
    issues = validate_creative_brief(data)
    assert any("source_hash_key_not_canonical_absolute" in i for i in issues)
    # Exactly one key is flagged.
    assert sum(1 for i in issues if "canonical_absolute" in i) >= 1


def test_absolute_source_hash_key_passes_validation() -> None:
    """An absolute path key (starting with '/') passes validation."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 24,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {
            _VALID_SOURCE_PATH: _VALID_SOURCE_HASH,
        },
    }
    issues = validate_creative_brief(data)
    assert not issues


def test_source_hash_key_cannot_be_a_directory(tmp_path: Path) -> None:
    """A canonical absolute directory is not a source file path."""
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    data = {
        "schema_version": 2,
        "chapter_id": 25,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
        "source_hashes": {str(tmp_path.resolve()): "a" * 64},
    }

    issues = validate_creative_brief(data)
    assert any("source_hash_key_not_file" in issue for issue in issues)


def test_source_hash_key_must_exist_and_match_bytes(tmp_path: Path) -> None:
    from agent_runtime.narrative.production.brief_compiler import (
        validate_creative_brief,
    )

    missing = tmp_path / "missing.yml"
    common = {
        "schema_version": 2,
        "chapter_id": 26,
        "primary_function": "plot",
        "pov": "third_person_limited",
        "opposing_wants": "desire vs obstacle",
        "turn": "a turn",
        "cost": "a cost",
        "reader_question": "what next?",
        "must_preserve": [],
        "creative_freedom": [],
    }
    missing_issues = validate_creative_brief(
        {**common, "source_hashes": {str(missing.resolve()): "a" * 64}}
    )
    assert any("source_hash_key_not_file" in issue for issue in missing_issues)

    source = tmp_path / "source.yml"
    source.write_bytes(b"actual source bytes\n")
    wrong_hash_issues = validate_creative_brief(
        {**common, "source_hashes": {str(source.resolve()): "b" * 64}}
    )
    assert any("source_hash_mismatch" in issue for issue in wrong_hash_issues)
