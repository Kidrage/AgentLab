from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
    assert observed["allow_writer_cli_fallback"] is False


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
