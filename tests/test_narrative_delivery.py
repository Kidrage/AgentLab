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
