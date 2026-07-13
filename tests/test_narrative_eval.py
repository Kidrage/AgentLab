from __future__ import annotations

import shutil
import sys
import types
from pathlib import Path

import typer
import yaml
from rich.console import Console
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from agent_runtime.cli.narrative_eval import register_narrative_eval_commands  # noqa: E402
from agent_runtime.narrative_eval import (  # noqa: E402
    _audit_history,
    _clear_chapter_attempt_outputs,
    _write_writer_contract_retry_feedback,
    _write_live_chapter_outputs,
    run_narrative_eval,
)


runner = CliRunner()


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_clear_chapter_attempt_outputs_archives_blocked_evidence(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "task_chapter"
    run_dir.mkdir(parents=True)
    (run_dir / "writer_role_session_capture.md").write_text("rejected", encoding="utf-8")
    _write_yaml(
        run_dir / "writer_output_contract.yml",
        {"status": "blocked", "issues": ["invalid candidate"]},
    )
    _write_yaml(
        run_dir / "live_generation_error.yml",
        {"status": "blocked", "error": "required output missing"},
    )
    _write_yaml(run_dir / "writer_retry_ledger.yml", {"status": "blocked"})

    _clear_chapter_attempt_outputs(run_dir)

    archive = run_dir / "rejected_attempts" / "resume_001"
    assert (archive / "writer_role_session_capture.md").read_text(encoding="utf-8") == "rejected"
    rejection = yaml.safe_load((archive / "rejection.yml").read_text(encoding="utf-8"))
    assert rejection["contract_issues"] == ["invalid candidate"]
    assert rejection["live_generation_error"] == "required output missing"
    assert "writer_retry_ledger.yml" in rejection["archived_files"]
    assert not (run_dir / "writer_output_contract.yml").exists()
    assert not (run_dir / "live_generation_error.yml").exists()


def test_writer_contract_retry_feedback_includes_character_ranges(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_yaml(
        run_dir / "chapter_packet.yml",
        {
            "chapter_intent": {
                "target_character_range": [4500, 5500],
                "hard_character_range": [3000, 8000],
            }
        },
    )

    _write_writer_contract_retry_feedback(
        run_dir,
        attempt=1,
        chapter=200,
        issues=["draft_character_count_out_of_range"],
    )

    feedback = yaml.safe_load(
        (run_dir / "writer_contract_retry_feedback.yml").read_text(encoding="utf-8")
    )
    assert feedback["draft_character_contract"] == {
        "target_character_range": [4500, 5500],
        "hard_character_range": [3000, 8000],
    }


def _writer_candidate_blocks(draft: str) -> str:
    outputs = {
        "fiction_draft.md": f"# Draft\n\n{draft}\n",
        "continuity_ledger.yml": yaml.safe_dump(
            {
                "schema_version": 1,
                "chapter": 1,
                "baseline_mode": "reset",
                "timeline": {"monotonic": True, "chapter_day": 1},
                "writer_marker": "preserve_me",
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        "state_transition_proposal.yml": yaml.safe_dump(
            {
                "schema_version": 1,
                "status": "candidate",
                "events": [
                    {
                        "event_type": "chapter_state_change",
                        "scope": "candidate_only",
                        "summary": "writer-authored",
                    }
                ],
                "requires_user_promotion": True,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        "narrative_delivery_receipt.yml": yaml.safe_dump(
            {"schema_version": 1, "status": "pass", "candidate_only": True},
            sort_keys=False,
            allow_unicode=True,
        ),
    }
    return "\n\n".join(
        f"<!-- AGENTLAB_EDIT: {name} -->\n{content}<!-- END AGENTLAB_EDIT -->"
        for name, content in outputs.items()
    )


def _copy_config_root(tmp_path: Path) -> Path:
    root = tmp_path / "AgentLab"
    (root / "config").mkdir(parents=True)
    for name in [
        "content_project_governance.yml",
        "agent_role_bindings.yml",
        "frontdesk_policy.yml",
        "model_catalog.yml",
        "worker_invocation_contracts.yml",
    ]:
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    return root


def _make_crown_project(root: Path) -> Path:
    project_root = root / "projects" / "Crown_of_Ash"
    (project_root / "production" / "bible").mkdir(parents=True)
    (project_root / "production" / "outlines").mkdir(parents=True)
    (project_root / "production" / "manuscript").mkdir(parents=True)
    (project_root / "production" / "bible" / "roles.md").write_text("# Roles\n", encoding="utf-8")
    (project_root / "production" / "outlines" / "main_outline.md").write_text("# Outline\n", encoding="utf-8")
    (project_root / "production" / "outlines" / "02_卷纲与章节路线.md").write_text(
        """# 卷纲与章节路线

## 第一卷：灰烬中觉醒

### 1-2 章：灰谷镇与逃亡

- 01：灰谷镇日常、火刑、师父死亡、烙印初热。
- 02：荒野逃亡、濒死、烙印激活、被教团密探发现。

### 3-5 章：地下图书馆

- 凯恩苏醒并确认烙印的代价。
- 伊莎贝拉隐瞒一次异常数据。
""",
        encoding="utf-8",
    )
    for chapter in range(1, 11):
        (project_root / "production" / "manuscript" / f"第{chapter:02d}章_旧稿.md").write_text(
            f"# Old Ch{chapter}\n旧稿作废。\n",
            encoding="utf-8",
        )
    _write_yaml(
        project_root / "project_artifact_index.yml",
        {
            "artifacts": [
                {"artifact_id": "project_bible", "status": "current", "production_path": "production/bible/"},
                {"artifact_id": "outline_set", "status": "current", "production_path": "production/outlines/"},
                {"artifact_id": "manuscript_series", "status": "deprecated", "production_path": "production/manuscript/"},
            ]
        },
    )
    _write_yaml(project_root / "project_brain" / "project_fact_snapshot.yml", {"project": "Crown_of_Ash", "event_count": 0})
    (project_root / "project_brain" / "project_fact_events.jsonl").write_text("", encoding="utf-8")
    (project_root / "project_brain" / "revision_log.jsonl").write_text("", encoding="utf-8")
    return project_root


def test_narrative_eval_reset_mock_generates_candidate_chapters_without_production_writes(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    production_before = {
        path.relative_to(project_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((project_root / "production" / "manuscript").glob("*.md"))
    }

    result = run_narrative_eval(
        root,
        "Crown_of_Ash",
        suite="crown_reset_acceptance_v1",
        mode="mock",
        chapters=[1, 2, 3],
        timestamp="20260705T000000Z",
    )

    eval_dir = root / result["acceptance_run_dir"]
    assert result["status"] == "warn"
    assert result["baseline"]["old_chapters_used_as_continuity_source"] is False
    assert (eval_dir / "longform_eval_report.yml").exists()
    assert (eval_dir / "chapter_quality_matrix.yml").exists()
    assert (eval_dir / "continuity_failure_report.yml").exists()
    assert (eval_dir / "series_scale_simulation.yml").exists()
    assert (eval_dir / "manuscript_reset_proposal.yml").exists()

    reset_proposal = yaml.safe_load((eval_dir / "manuscript_reset_proposal.yml").read_text(encoding="utf-8"))
    assert len(reset_proposal["deprecated_sources"]) == 10
    assert reset_proposal["production_modified"] is False

    l2_chapters = result["layers"]["L2_real_chapter_sample"]["chapters"]
    assert [item["chapter"] for item in l2_chapters] == [1, 2, 3]
    for item in l2_chapters:
        run_dir = root / item["run_dir"]
        packet = yaml.safe_load((run_dir / "chapter_packet.yml").read_text(encoding="utf-8"))
        workflow = yaml.safe_load((run_dir / "workflow_plan.yml").read_text(encoding="utf-8"))
        expected_baseline = "reset" if item["chapter"] == 1 else "continuation"
        assert packet["baseline_mode"] == expected_baseline
        assert packet["chapter_intent"]["status"] == "planned"
        assert item["task_id"].startswith("task_narrative_eval_ch")
        assert workflow["route"]["route_key"] == "narrative_light_chapter"
        assert not any(source.startswith("production/manuscript/") for source in packet["previous_chapters"])
        assert item["delivery"]["valid"] is True
        assert (run_dir / "narrative_delivery_receipt.yml").exists()

    ch1_packet = yaml.safe_load((root / l2_chapters[0]["run_dir"] / "chapter_packet.yml").read_text(encoding="utf-8"))
    ch2_packet = yaml.safe_load((root / l2_chapters[1]["run_dir"] / "chapter_packet.yml").read_text(encoding="utf-8"))
    ch3_packet = yaml.safe_load((root / l2_chapters[2]["run_dir"] / "chapter_packet.yml").read_text(encoding="utf-8"))
    assert ch1_packet["previous_chapters"] == []
    assert ch1_packet["chapter_intent"]["source_kind"] == "exact_chapter_beat"
    assert "灰谷镇日常" in ch1_packet["chapter_intent"]["plot_state_change"]
    assert ch2_packet["previous_candidate_sources"] == [
        "runs/task_narrative_eval_ch01_20260705T000000Z/fiction_draft.md",
        "runs/task_narrative_eval_ch01_20260705T000000Z/continuity_ledger.yml",
        "runs/task_narrative_eval_ch01_20260705T000000Z/state_transition_proposal.yml",
    ]
    assert ch2_packet["story_authority"]["candidate_fact_ledger"].endswith(
        "/candidate_fact_ledger.yml"
    )
    ch2_candidate_facts = yaml.safe_load(
        (root / l2_chapters[1]["run_dir"] / "candidate_fact_ledger.yml").read_text(encoding="utf-8")
    )
    assert ch2_candidate_facts["status"] == "candidate"
    assert ch2_candidate_facts["promoted"] is False
    assert ch2_candidate_facts["through_chapter"] == 1
    assert ch2_candidate_facts["event_count"] == 1
    assert ch3_packet["previous_candidate_sources"] == [
        "runs/task_narrative_eval_ch02_20260705T000000Z/fiction_draft.md",
        "runs/task_narrative_eval_ch02_20260705T000000Z/continuity_ledger.yml",
        "runs/task_narrative_eval_ch02_20260705T000000Z/state_transition_proposal.yml",
    ]
    ch3_candidate_facts = yaml.safe_load(
        (root / l2_chapters[2]["run_dir"] / "candidate_fact_ledger.yml").read_text(encoding="utf-8")
    )
    assert ch3_candidate_facts["through_chapter"] == 2
    assert ch3_candidate_facts["event_count"] == 2
    assert ch3_packet["chapter_intent"]["source_kind"] == "chapter_range_phase"
    ch2_ledger = yaml.safe_load(
        (root / l2_chapters[1]["run_dir"] / "continuity_ledger.yml").read_text(encoding="utf-8")
    )
    assert ch2_ledger["baseline_mode"] == "continuation"

    production_after = {
        path.relative_to(project_root).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((project_root / "production" / "manuscript").glob("*.md"))
    }
    assert production_after == production_before


def test_narrative_eval_blocks_generation_when_fact_snapshot_missing(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    (project_root / "project_brain" / "project_fact_snapshot.yml").unlink()

    result = run_narrative_eval(root, "Crown_of_Ash", mode="mock", timestamp="20260705T010000Z")

    assert result["status"] == "fail"
    assert result["layers"]["L0_fact_source_health"]["live_generation_blocked"] is True
    assert result["layers"]["L2_real_chapter_sample"]["status"] == "blocked"
    generated_runs = list((project_root / "runs").glob("task_narrative_eval_ch*")) if (project_root / "runs").exists() else []
    assert generated_runs == []


def test_narrative_eval_resume_reuses_valid_chapters_and_rebuilds_continuity_chain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)
    timestamp = "20260705T005000Z"

    first = run_narrative_eval(
        root,
        "Crown_of_Ash",
        mode="mock",
        chapters=[1, 2, 3],
        timestamp=timestamp,
        resume_valid=True,
    )
    assert first["layers"]["L2_real_chapter_sample"]["status"] == "pass"
    assert all(
        chapter.get("resumed_existing") is not True
        for chapter in first["layers"]["L2_real_chapter_sample"]["chapters"]
    )

    def fail_if_regenerated(*args, **kwargs):
        raise AssertionError("valid chapter should have been resumed")

    monkeypatch.setattr("agent_runtime.narrative_eval._write_mock_chapter_outputs", fail_if_regenerated)
    resumed = run_narrative_eval(
        root,
        "Crown_of_Ash",
        mode="mock",
        chapters=[1, 2, 3],
        timestamp=timestamp,
        resume_valid=True,
        stop_on_block=True,
    )

    l2 = resumed["layers"]["L2_real_chapter_sample"]
    assert l2["status"] == "pass"
    assert l2["completed_chapter_count"] == 3
    assert all(chapter["resumed_existing"] is True for chapter in l2["chapters"])
    eval_dir = root / resumed["acceptance_run_dir"]
    checkpoint = yaml.safe_load((eval_dir / "generation_checkpoint.yml").read_text(encoding="utf-8"))
    assert checkpoint["status"] == "complete"
    assert checkpoint["completed_chapters"] == [1, 2, 3]


def test_narrative_eval_stop_on_block_prevents_later_chapter_generation(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)

    result = run_narrative_eval(
        root,
        "Crown_of_Ash",
        mode="live",
        chapters=[1, 2, 3],
        timestamp="20260705T005500Z",
        stop_on_block=True,
    )

    l2 = result["layers"]["L2_real_chapter_sample"]
    assert l2["status"] == "blocked"
    assert [chapter["chapter"] for chapter in l2["chapters"]] == [1]
    assert not (project_root / "runs" / "task_narrative_eval_ch02_20260705T005500Z").exists()
    checkpoint = yaml.safe_load(
        (root / result["acceptance_run_dir"] / "generation_checkpoint.yml").read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "blocked"
    assert checkpoint["blocking_chapter"] == 1
    assert checkpoint["next_chapter"] == 2
    assert checkpoint["resume_chapter"] == 1


def test_history_audit_does_not_require_review_for_light_chapter_runs(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_light_chapter_complete"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("write Crown chapter 1", encoding="utf-8")
    _write_yaml(run_dir / "workflow_plan.yml", {"route": {"route_key": "narrative_light_chapter", "agents": ["Supervisor", "Writer"]}})
    _write_yaml(run_dir / "chapter_packet.yml", {"chapter": 1})
    (run_dir / "fiction_draft.md").write_text("# Draft\n\n正文", encoding="utf-8")
    _write_yaml(run_dir / "continuity_ledger.yml", {"chapter": 1})
    _write_yaml(run_dir / "state_transition_proposal.yml", {"chapter": 1})
    _write_yaml(run_dir / "narrative_delivery_receipt.yml", {"status": "pass"})

    audit = _audit_history(project_root)

    assert all(item["task_id"] != "task_light_chapter_complete" for item in audit["incomplete_historical_narrative_runs"])


def test_history_audit_does_not_treat_heavy_audit_bundle_as_chapter_run(
    tmp_path: Path,
) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_narrative_heavy_audit_ch001_ch020"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text(
        "Audit Crown chapters 1-20",
        encoding="utf-8",
    )
    _write_yaml(run_dir / "narrative_audit_manifest.yml", {"chapter_range": [1, 20]})

    audit = _audit_history(project_root)

    assert all(
        item["task_id"] != run_dir.name
        for item in audit["incomplete_historical_narrative_runs"]
    )


def test_history_audit_classifies_live_generation_error_separately(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    run_dir = project_root / "runs" / "task_live_guard_blocked"
    run_dir.mkdir(parents=True)
    (run_dir / "user_request.md").write_text("write Crown chapter 1", encoding="utf-8")
    _write_yaml(run_dir / "workflow_plan.yml", {"route": {"route_key": "narrative_light_chapter", "agents": ["Supervisor", "Writer"]}})
    _write_yaml(run_dir / "chapter_packet.yml", {"chapter": 1})
    _write_yaml(
        run_dir / "live_generation_error.yml",
        {
            "schema_version": 1,
            "status": "blocked",
            "agent": "Writer",
            "result_status": "blocked",
            "error": "live narrative eval requires an AgentLab Writer role-session packet",
        },
    )

    audit = _audit_history(project_root)

    assert all(item["task_id"] != "task_live_guard_blocked" for item in audit["incomplete_historical_narrative_runs"])
    assert any(item["task_id"] == "task_live_guard_blocked" for item in audit["blocked_live_generation_runs"])


def test_narrative_eval_scale_simulation_has_1500_chapter_ledgers(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)

    result = run_narrative_eval(root, "Crown_of_Ash", mode="audit-only", timestamp="20260705T020000Z")
    eval_dir = root / result["acceptance_run_dir"]
    simulation = yaml.safe_load((eval_dir / "series_scale_simulation.yml").read_text(encoding="utf-8"))

    assert simulation["chapter_count"] == 1500
    assert simulation["target_total_chapters"] == 1500
    assert simulation["simulation_scope"] == "governance_ledger_only"
    assert simulation["text_generation"]["draft_chapters_generated"] == 0
    assert simulation["text_generation"]["draft_text_generated"] is False
    assert simulation["timeline_monotonic"] is True
    assert simulation["foreshadowing_statuses_valid"] is True
    assert simulation["character_arcs_have_phase_changes"] is True
    assert simulation["governance_cadence"]["continuity_batch_audit"] == "every 3 chapters"
    assert "project_fact_snapshot.yml" in simulation["memory_contract"]["required_inputs"]
    assert "narrative-eval or narrative_heavy_audit pass" in simulation["promotion_gates"]
    for filename in simulation["ledgers"].values():
        assert (eval_dir / filename).exists()


def test_narrative_eval_cli_run_on_temp_root(tmp_path: Path) -> None:
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)
    local_app = typer.Typer()
    register_narrative_eval_commands(local_app, root, Console(width=120))

    result = runner.invoke(
        local_app,
        [
            "narrative-eval",
            "run",
            "--project",
            "Crown_of_Ash",
            "--suite",
            "crown_reset_acceptance_v1",
            "--mode",
            "mock",
            "--chapters",
            "1-3",
            "--timestamp",
            "20260705T030000Z",
        ],
    )

    assert result.exit_code == 0
    data = yaml.safe_load(result.output)
    assert data["acceptance_run_dir"] == "acceptance_runs/narrative_eval/Crown_of_Ash/crown_reset_acceptance_v1/20260705T030000Z"
    assert data["allow_writer_cli_fallback"] is False


def test_live_narrative_eval_stops_before_reviewer_when_writer_fails(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        calls.append(agent_name)
        return types.SimpleNamespace(
            status="blocked_user_decision",
            content="# blocked",
            error="writer cli failed",
            provider="agentlab-cli-executor",
            model="deepseek-v4-pro",
        )

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    monkeypatch.setitem(
        sys.modules,
        "workflow_plan",
        types.SimpleNamespace(build_workflow_plan=lambda *args, **kwargs: types.SimpleNamespace()),
    )
    monkeypatch.setattr(
        "agent_runtime.narrative_eval._try_writer_cli_fallback",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fallback must be opt-in")),
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "user_request.md").write_text("write chapter", encoding="utf-8")

    _write_live_chapter_outputs(tmp_path, run_dir, "Crown_of_Ash", "task_live", 1, [])

    assert calls == ["Writer"]
    assert not (run_dir / "fiction_draft.md").exists()
    error = yaml.safe_load((run_dir / "live_generation_error.yml").read_text(encoding="utf-8"))
    assert error["agent"] == "Writer"
    assert error["result_status"] == "blocked_user_decision"


def test_live_narrative_eval_report_includes_writer_failure_summary(tmp_path: Path, monkeypatch) -> None:
    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        return types.SimpleNamespace(
            status="blocked_user_decision",
            content="",
            error="writer cli failed",
            provider="agentlab-cli-executor",
            model="deepseek-v4-pro",
        )

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    monkeypatch.setitem(
        sys.modules,
        "workflow_plan",
        types.SimpleNamespace(build_workflow_plan=lambda *args, **kwargs: types.SimpleNamespace()),
    )
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)

    result = run_narrative_eval(
        root,
        "Crown_of_Ash",
        mode="live",
        chapters=[1],
        timestamp="20260705T040000Z",
        writer_worker="claude_code",
    )

    assert result["status"] == "fail"
    chapter = result["layers"]["L2_real_chapter_sample"]["chapters"][0]
    assert chapter["live_generation_error"]["agent"] == "Writer"
    assert chapter["live_generation_error"]["result_status"] == "blocked_user_decision"
    assert chapter["live_generation_error"]["path"].endswith("/live_generation_error.yml")


def test_live_narrative_eval_blocks_without_writer_role_session(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        calls.append(agent_name)
        return types.SimpleNamespace(status="completed", content="# Draft", error=None, provider="test", model="test")

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    root = _copy_config_root(tmp_path)
    _make_crown_project(root)

    result = run_narrative_eval(
        root,
        "Crown_of_Ash",
        mode="live",
        chapters=[1],
        timestamp="20260705T041000Z",
    )

    assert result["status"] == "fail"
    assert calls == []
    chapter = result["layers"]["L2_real_chapter_sample"]["chapters"][0]
    assert chapter["live_generation_error"]["result_status"] == "blocked"
    assert chapter["live_generation_error"]["role_session_guard"]["reason"] == "missing_role_session"


def test_live_narrative_eval_writes_light_outputs_after_writer_complete(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        calls.append(agent_name)
        assert kwargs["allow_cli_api_fallback"] is False
        content = _writer_candidate_blocks("正文段落。" * 900) if agent_name == "Writer" else "verdict: pass\n"
        return types.SimpleNamespace(
            status="completed",
            content=content,
            error=None,
            provider="test",
            model="test",
        )

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    monkeypatch.setitem(
        sys.modules,
        "workflow_plan",
        types.SimpleNamespace(build_workflow_plan=lambda *args, **kwargs: types.SimpleNamespace()),
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "user_request.md").write_text("write chapter", encoding="utf-8")
    _write_yaml(run_dir / "live_generation_error.yml", {"status": "blocked", "message": "stale"})

    _write_live_chapter_outputs(tmp_path, run_dir, "Crown_of_Ash", "task_live", 1, [])

    assert not (run_dir / "live_generation_error.yml").exists()
    assert calls == ["Writer"]
    assert (run_dir / "fiction_draft.md").exists()
    assert not (run_dir / "fiction_review.yml").exists()
    assert (run_dir / "continuity_ledger.yml").exists()
    assert (run_dir / "state_transition_proposal.yml").exists()
    assert (run_dir / "narrative_delivery_receipt.yml").exists()
    contract = yaml.safe_load((run_dir / "writer_output_contract.yml").read_text(encoding="utf-8"))
    assert contract["status"] == "pass"
    assert contract["harness_generated_story_state"] is False
    ledger = yaml.safe_load((run_dir / "continuity_ledger.yml").read_text(encoding="utf-8"))
    assert ledger["writer_marker"] == "preserve_me"
    request = yaml.safe_load((run_dir / "live_generation_request.yml").read_text(encoding="utf-8"))
    assert request["status"] == "ready_for_internal_writer_role_session"
    assert request["execution_scope"] == "internal_agentlab_writer_role_session"
    assert request["candidate_only"] is True
    assert request["writer_role_session_required"] is True
    assert request["writer_cli_fallback_allowed"] is False
    assert request["provider_surface_fallback_allowed"] is False
    assert request["required_outputs"] == [
        "fiction_draft.md",
        "continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_delivery_receipt.yml",
    ]
    assert request["supplementary_outputs"] == ["artifact_lineage.yml"]


def test_live_narrative_eval_delegates_capacity_failure_without_local_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "user_request.md").write_text("write chapter", encoding="utf-8")
    log_path = run_dir / "command_logs" / "writer.stderr.txt"
    log_path.parent.mkdir()
    log_path.write_text(
        "Error: quota exhausted. Resets in 1h2m3s.\n",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        calls.append({"agent_name": agent_name, "kwargs": kwargs})
        return types.SimpleNamespace(
            status="blocked_user_decision",
            content="",
            error="CLI agent quota_exhausted (exit 1).",
            provider="agentlab-cli-executor",
            model="deepseek-v4-pro",
            raw_usage={
                "failure_class": "quota_exhausted",
                "capacity_route": "Writer",
                "capacity_pool": "deepseek_metered_api",
                "capacity_status": "blocked",
                "capacity_reset_at": "2026-07-13T12:00:00Z",
                "cli_log_path": str(log_path),
                "command_id": "cmd_0001",
            },
        )

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    monkeypatch.setitem(
        sys.modules,
        "workflow_plan",
        types.SimpleNamespace(build_workflow_plan=lambda *args, **kwargs: types.SimpleNamespace()),
    )

    _write_live_chapter_outputs(
        tmp_path,
        run_dir,
        "Crown_of_Ash",
        "task_live",
        85,
        [],
    )

    assert calls == [{
        "agent_name": "Writer",
        "kwargs": {
            "allow_cli_api_fallback": False,
        },
    }]
    assert not (run_dir / "writer_retry_ledger.yml").exists()
    error = yaml.safe_load((run_dir / "live_generation_error.yml").read_text(encoding="utf-8"))
    assert error["error"] == "CLI agent quota_exhausted (exit 1)."
    assert error["failure_class"] == "quota_exhausted"
    assert error["capacity_route"] == "Writer"
    assert error["capacity_pool"] == "deepseek_metered_api"
    assert error["capacity_status"] == "blocked"
    assert error["capacity_reset_at"] == "2026-07-13T12:00:00Z"
    assert "retry_after_seconds" not in error
    request = yaml.safe_load(
        (run_dir / "live_generation_request.yml").read_text(encoding="utf-8")
    )
    assert request["model_capacity_governance"] == "centralized"


def test_live_narrative_eval_retries_one_full_contract_redo(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "user_request.md").write_text("write chapter", encoding="utf-8")
    calls: list[str] = []
    complete = _writer_candidate_blocks("正文段落。" * 900)
    incomplete = complete.split(
        "<!-- AGENTLAB_EDIT: narrative_delivery_receipt.yml -->",
        1,
    )[0]

    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        calls.append(agent_name)
        if len(calls) == 2:
            feedback = yaml.safe_load(
                (run_dir / "writer_contract_retry_feedback.yml").read_text(
                    encoding="utf-8"
                )
            )
            assert feedback["status"] == "correction_required"
            assert feedback["issues"] == [
                "missing_writer_output:narrative_delivery_receipt.yml"
            ]
            assert feedback["required_envelopes"]["state_transition_proposal.yml"][
                "status"
            ] == "candidate"
            assert feedback["required_envelopes"]["narrative_delivery_receipt.yml"][
                "status"
            ] == "pass"
        return types.SimpleNamespace(
            status="completed",
            content=incomplete if len(calls) == 1 else complete,
            error=None,
            provider="agentlab-cli-executor",
            model="deepseek-v4-pro",
            raw_usage={"command_id": f"cmd_{len(calls):04d}"},
        )

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    monkeypatch.setitem(
        sys.modules,
        "workflow_plan",
        types.SimpleNamespace(build_workflow_plan=lambda *args, **kwargs: types.SimpleNamespace()),
    )

    _write_live_chapter_outputs(tmp_path, run_dir, "Crown_of_Ash", "task_live", 1, [])

    assert calls == ["Writer", "Writer"]
    assert (run_dir / "fiction_draft.md").exists()
    retry = yaml.safe_load((run_dir / "writer_retry_ledger.yml").read_text(encoding="utf-8"))
    assert retry["status"] == "recovered"
    assert retry["limits"]["full_contract_redos"] == 1
    assert retry["attempts"][0]["retry_kind"] == "full_contract_redo"
    assert "missing_writer_output:narrative_delivery_receipt.yml" in retry["attempts"][0]["contract_issues"]
    assert retry["attempts"][0]["snapshots"] == {
        "writer_role_session_capture.md": "writer_retry_attempt_01_capture.md",
        "writer_output_contract.yml": "writer_retry_attempt_01_contract.yml",
    }
    assert retry["attempts"][1]["materialized"] is True


def test_live_narrative_eval_failed_retry_cannot_reuse_stale_candidate_outputs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        return types.SimpleNamespace(
            status="blocked_user_decision",
            content="",
            error="transient auth failure",
            provider="agentlab-cli-executor",
            model="deepseek-v4-pro",
        )

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    monkeypatch.setitem(
        sys.modules,
        "workflow_plan",
        types.SimpleNamespace(build_workflow_plan=lambda *args, **kwargs: types.SimpleNamespace()),
    )
    root = _copy_config_root(tmp_path)
    project_root = _make_crown_project(root)
    timestamp = "20260705T042000Z"
    run_dir = project_root / "runs" / f"task_narrative_eval_ch01_{timestamp}"
    run_dir.mkdir(parents=True)
    for filename in [
        "fiction_draft.md",
        "continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_delivery_receipt.yml",
    ]:
        (run_dir / filename).write_text("stale\n", encoding="utf-8")

    result = run_narrative_eval(
        root,
        "Crown_of_Ash",
        mode="live",
        chapters=[1],
        timestamp=timestamp,
        writer_worker="claude_code",
        stop_on_block=True,
    )

    chapter = result["layers"]["L2_real_chapter_sample"]["chapters"][0]
    assert chapter["delivery"]["valid"] is False
    assert chapter["live_generation_error"]["result_status"] == "blocked_user_decision"
    assert not (run_dir / "fiction_draft.md").exists()
    assert not (run_dir / "continuity_ledger.yml").exists()
    assert not (run_dir / "state_transition_proposal.yml").exists()
    assert not (run_dir / "narrative_delivery_receipt.yml").exists()


def test_live_narrative_eval_cli_fallback_completes_light_outputs(tmp_path: Path, monkeypatch) -> None:
    def fake_run_agent_model(root, plan, agent_name, output_path, apply_patches=False, **kwargs):
        return types.SimpleNamespace(
            status="blocked_user_decision",
            content="",
            error="Connection error.",
            provider="deepseek",
            model="deepseek-v4-flash",
        )

    def fake_subprocess_run(command, cwd, text, capture_output, timeout, check):
        run_dir.joinpath("writer_cli_fallback_capture.md").write_text(
            _writer_candidate_blocks("正文段落。" * 900),
            encoding="utf-8",
        )
        return types.SimpleNamespace(returncode=0, stdout="Agent report written", stderr="")

    monkeypatch.setitem(sys.modules, "agent_runner", types.SimpleNamespace(run_agent_model=fake_run_agent_model))
    monkeypatch.setitem(
        sys.modules,
        "workflow_plan",
        types.SimpleNamespace(build_workflow_plan=lambda *args, **kwargs: types.SimpleNamespace()),
    )
    monkeypatch.setattr("agent_runtime.narrative_eval.subprocess.run", fake_subprocess_run)

    root = tmp_path
    (root / "agentlab.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "user_request.md").write_text("write chapter", encoding="utf-8")

    _write_live_chapter_outputs(
        root,
        run_dir,
        "Crown_of_Ash",
        "task_live",
        1,
        [],
        allow_writer_cli_fallback=True,
    )

    assert not (run_dir / "live_generation_error.yml").exists()
    assert (run_dir / "live_writer_cli_fallback.yml").exists()
    assert (run_dir / "fiction_draft.md").exists()
    assert (run_dir / "continuity_ledger.yml").exists()
    assert (run_dir / "state_transition_proposal.yml").exists()
    assert (run_dir / "narrative_delivery_receipt.yml").exists()
