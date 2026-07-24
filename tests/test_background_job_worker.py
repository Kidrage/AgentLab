from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from agent_runtime.background_job_controller import (
    create_crown_delivery_job,
    load_job_state,
    schedule_next_attempt,
)
from agent_runtime.background_job_worker import execute_action, run_attempt


def _request(root: Path, action: str, *, end_chapter: int = 2) -> dict:
    return {
        "schema_version": 1,
        "job_id": "job-1",
        "project": "Crown_of_Ash",
        "attempt_id": f"attempt-1-{action}",
        "idempotency_key": f"job-1:{action}",
        "action": action,
        "candidate_only": True,
        "production_allowed": False,
        "agentlab_root": str(root),
        "batch": {"number": 1, "start": 1, "end": end_chapter},
        "config": {
            "narrative_adapter": "crown",
            "eval_id": "eval-v1",
            "suite": "suite-v1",
            "start_chapter": 1,
            "end_chapter": end_chapter,
            "batch_size": 10,
            "heavy_audit_cadence": 10,
            "writer_worker": "writer-worker",
            "chapter_state_plan": "runs/shared/chapter_state_plan.yml",
            "writer_budget": "frugal",
            "allow_writer_cli_fallback": False,
        },
    }


def _project(root: Path) -> Path:
    project = root / "projects" / "Crown_of_Ash"
    (project / "project_brain").mkdir(parents=True)
    (project / "project_brain/project_fact_snapshot.yml").write_text("facts: []\n")
    (project / "project_artifact_index.yml").write_text("artifacts: []\n")
    (project / "production/manuscript").mkdir(parents=True)
    (project / "production/manuscript/.gitkeep").write_text("")
    (project / "runs/shared").mkdir(parents=True)
    (project / "runs/shared/chapter_state_plan.yml").write_text("status: candidate\n")
    return project


def test_preflight_enforces_candidate_boundary_and_structured_plan(tmp_path: Path) -> None:
    _project(tmp_path)
    request = _request(tmp_path, "preflight")
    with patch(
        "agent_runtime.narrative_delivery.validate_chapter_state_plan",
        return_value={"status": "pass", "issues": []},
    ):
        result = execute_action(request)
    assert result["outcome"] == "success"
    assert result["result"]["status"] == "pass"

    (tmp_path / "projects/Crown_of_Ash/production/manuscript/chapter.md").write_text(
        "forbidden"
    )
    with patch(
        "agent_runtime.narrative_delivery.validate_chapter_state_plan",
        return_value={"status": "pass", "issues": []},
    ):
        blocked = execute_action(request)
    assert blocked["outcome"] == "failed"
    assert "production_manuscript_not_empty" in blocked["result"]["issues"]


def test_rag_preflight_requires_current_blueprint_seal_and_knowledge_snapshot(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    request = _request(tmp_path, "preflight")
    request["config"]["knowledge_contract_required"] = True
    with patch(
        "agent_runtime.narrative_delivery.validate_chapter_state_plan",
        return_value={"status": "pass", "issues": []},
    ), patch(
        "agent_runtime.narrative.blueprint_validation.validate_blueprint_seal",
        return_value={"status": "blocked", "issues": ["receipt_missing"]},
    ):
        result = execute_action(request)

    assert result["outcome"] == "failed"
    assert "blueprint_seal_invalid" in result["result"]["issues"]
    assert "missing_knowledge_index_snapshot" in result["result"]["issues"]


def test_final_acceptance_builds_candidate_package_not_production(tmp_path: Path) -> None:
    project = _project(tmp_path)
    for chapter in (1, 2):
        run = project / "runs" / f"task_narrative_eval_ch{chapter:02d}_eval-v1"
        run.mkdir(parents=True)
        (run / "fiction_draft.md").write_text(
            f"# Chapter {chapter}\n\nCandidate prose {chapter}.\n",
            encoding="utf-8",
        )
        (run / "narrative_delivery_receipt.yml").write_text(
            "status: pass\nvalid: true\n",
            encoding="utf-8",
        )
    request = _request(tmp_path, "final_acceptance")
    request["job_id"] = "job-1"
    with patch(
        "agent_runtime.crown_candidate_audit.write_crown_completion_batch_audit",
        return_value={"status": "pass", "issues": []},
    ), patch(
        "agent_runtime.narrative_delivery.validate_narrative_delivery",
        return_value={"valid": True},
    ):
        result = execute_action(request)

    assert result["outcome"] == "success"
    package = Path(result["result"]["candidate_package"])
    assert package.is_file()
    assert package.read_text().count("<!-- AGENTLAB_CHAPTER_BOUNDARY") == 2
    assert list((project / "production/manuscript").iterdir()) == [
        project / "production/manuscript/.gitkeep"
    ]


def test_generation_forwards_writer_budget_to_narrative_runtime(tmp_path: Path) -> None:
    _project(tmp_path)
    request = _request(tmp_path, "generate_batch")
    request["config"]["allow_writer_cli_fallback"] = True
    observed: dict = {}

    def fake_run(root, project, **kwargs):
        observed.update(kwargs)
        return {
            "status": "pass",
            "layers": {
                "L2_real_chapter_sample": {
                    "status": "pass",
                    "completed_chapter_count": 2,
                    "selected_chapter_count": 2,
                }
            },
        }

    with patch(
        "agent_runtime.narrative_eval.run_narrative_eval",
        side_effect=fake_run,
    ):
        result = execute_action(request)

    assert result["outcome"] == "success"
    assert observed["writer_budget_mode"] == "frugal"
    assert observed["allow_writer_cli_fallback"] is True


def test_generation_network_failure_returns_durable_retry_wait(tmp_path: Path) -> None:
    _project(tmp_path)
    request = _request(tmp_path, "generate_batch")
    request["config"]["transient_retry_seconds"] = 60

    report = {
        "status": "fail",
        "layers": {
            "L2_real_chapter_sample": {
                "status": "blocked",
                "completed_chapter_count": 0,
                "selected_chapter_count": 2,
                "chapters": [
                    {
                        "chapter": 1,
                        "live_generation_error": {
                            "failure_class": "network_required",
                            "error": "FailedToOpenSocket",
                        },
                    }
                ],
            }
        },
    }
    with patch(
        "agent_runtime.narrative_eval.run_narrative_eval",
        return_value=report,
    ), patch(
        "agent_runtime.background_job_worker._utc_now",
        return_value="2026-07-23T07:00:00+00:00",
    ):
        result = execute_action(request)

    assert result["outcome"] == "retry_wait"
    assert result["retry_at"] == "2026-07-23T07:01:00+00:00"
    assert result["result"]["reason"] == "network_required"


def test_heavy_audit_network_failure_returns_durable_retry_wait(tmp_path: Path) -> None:
    _project(tmp_path)
    request = _request(tmp_path, "heavy_audit", end_chapter=10)
    request["config"]["transient_retry_seconds"] = 60

    with patch(
        "agent_runtime.narrative.audit.background.prepare_and_precheck_audit",
        return_value={
            "prepared": {"status": "ready", "issues": []},
            "precheck": {"status": "pass", "blocking_codes": []},
        },
    ), patch(
        "agent_runtime.narrative.audit.runtime.run_single_judge_pipeline",
        return_value={
            "success": False,
            "blocked_reason": "CLI agent network_required (exit 1).",
        },
    ), patch(
        "agent_runtime.background_job_worker._utc_now",
        return_value="2026-07-18T07:00:00+00:00",
    ):
        result = execute_action(request)

    assert result["outcome"] == "retry_wait"
    assert result["retry_at"] == "2026-07-18T07:01:00+00:00"
    assert result["result"]["reason"] == "network_required"
    assert result["result"]["provider_failure_reason"].startswith("CLI agent")


def test_heavy_audit_result_persists_source_manifest_binding(tmp_path: Path) -> None:
    project = _project(tmp_path)
    request = _request(tmp_path, "heavy_audit", end_chapter=1)
    request["batch"] = {"number": 1, "start": 1, "end": 1}
    source = project / "runs" / "source-ch01" / "fiction_draft.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Chapter 1\n\nCandidate.\n", encoding="utf-8")
    import hashlib

    manifest_path = project / "runs" / "heavy-source-manifest.yml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "chapter": 1,
                        "files": {
                            "fiction_draft.md": {
                                "path": source.relative_to(project).as_posix(),
                                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                            }
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    decision = MagicMock()
    decision.requires_revision = False
    decision.to_dict.return_value = {"status": "pass", "allow_seal": True}

    def successful_pipeline(_root, *, project, task_id, budget_mode):
        run_dir = tmp_path / "projects" / project / "runs" / task_id
        run_dir.mkdir(parents=True)
        for name in (
            "fiction_review.yml",
            "continuity_failure_report.yml",
            "narrative_quality_scorecard.yml",
        ):
            (run_dir / name).write_text("status: pass\nfindings: []\n", encoding="utf-8")
        return {"success": True}

    with patch(
        "agent_runtime.narrative.audit.background.prepare_and_precheck_audit",
        return_value={
            "prepared": {
                "status": "ready",
                "issues": [],
                "manifest_path": str(manifest_path),
            },
            "precheck": {"status": "pass", "blocking_codes": []},
        },
    ), patch(
        "agent_runtime.narrative.audit.runtime.run_single_judge_pipeline",
        side_effect=successful_pipeline,
    ), patch(
        "agent_runtime.narrative.audit.background.run_tiered_followup",
        return_value={"status": "pass"},
    ), patch(
        "agent_runtime.narrative.audit.gate.evaluate_narrative_seal",
        return_value=decision,
    ):
        result = execute_action(request)

    assert result["outcome"] == "success"
    heavy = result["result"]
    assert heavy["audit_source_manifest_path"] == str(manifest_path)
    assert heavy["audit_source_manifest_sha256"] == hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()


def test_worker_always_writes_failure_receipt_for_exception(tmp_path: Path) -> None:
    _project(tmp_path)
    create_crown_delivery_job(
        tmp_path,
        project="Crown_of_Ash",
        job_id="job-1",
        eval_id="eval-v1",
        start_chapter=1,
        end_chapter=2,
        writer_worker="writer-worker",
        chapter_state_plan="runs/shared/chapter_state_plan.yml",
    )
    attempt = schedule_next_attempt(
        tmp_path, project="Crown_of_Ash", job_id="job-1"
    )
    with patch(
        "agent_runtime.background_job_worker.execute_action",
        side_effect=RuntimeError("synthetic crash"),
    ):
        code = run_attempt(
            tmp_path,
            project="Crown_of_Ash",
            job_id="job-1",
            attempt_id=attempt["attempt_id"],
        )

    assert code == 1
    receipt_path = (
        tmp_path
        / "projects/Crown_of_Ash/background_jobs/job-1/attempts"
        / attempt["attempt_id"]
        / "process_receipt.yml"
    )
    receipt = yaml.safe_load(receipt_path.read_text())
    assert receipt["outcome"] == "failed_recoverable"
    assert receipt["result"]["reason"] == "RuntimeError: synthetic crash"
    state = load_job_state(tmp_path, "Crown_of_Ash", "job-1")
    assert state["active_attempt"]["attempt_id"] == attempt["attempt_id"]
