from pathlib import Path
import hashlib
import io
import subprocess

import pytest
import typer
from rich.console import Console
from typer.testing import CliRunner

from agent_runtime.project_reset import (
    ActiveProjectResetError,
    ProjectResetApplyError,
    ProjectResetError,
    apply_project_reset,
    plan_project_reset,
)
from agent_runtime.cli.project_reset import register_project_reset_commands


def _project(root: Path) -> Path:
    project = root / "projects" / "Crown_of_Ash"
    (project / "runs" / "old-run").mkdir(parents=True)
    (project / "runs" / "old-run" / "fiction_draft.md").write_text(
        "legacy prose\n", encoding="utf-8"
    )
    return project


def test_reset_plan_is_blocked_by_active_collaboration_lock(tmp_path: Path) -> None:
    _project(tmp_path)
    locks = tmp_path / ".agents" / "locks"
    locks.mkdir(parents=True)
    (locks / "crown-writing.lock").write_text(
        "agent: codex\nstatus: in_progress\npaths:\n  - projects/Crown_of_Ash/\n",
        encoding="utf-8",
    )

    with pytest.raises(ActiveProjectResetError, match="crown-writing.lock"):
        plan_project_reset(
            tmp_path,
            project="Crown_of_Ash",
            targets=("runs",),
        )

    assert not (tmp_path / "projects" / "Crown_of_Ash" / "reset_manifests").exists()


def test_reset_plan_is_blocked_by_active_background_job(tmp_path: Path) -> None:
    project = _project(tmp_path)
    job = project / "background_jobs" / "ch01-ch20"
    job.mkdir(parents=True)
    (job / "job_state.yml").write_text(
        "project: Crown_of_Ash\nstatus: generating\nactive_attempt:\n  attempt_id: attempt-1\n",
        encoding="utf-8",
    )

    with pytest.raises(ActiveProjectResetError, match="ch01-ch20"):
        plan_project_reset(
            tmp_path,
            project="Crown_of_Ash",
            targets=("runs", "background_jobs"),
        )


@pytest.mark.parametrize("target", ("", ".", "..", "../NovelGen", "runs/*", "/tmp/runs"))
def test_reset_plan_rejects_broad_or_escaping_targets(
    tmp_path: Path, target: str
) -> None:
    _project(tmp_path)

    with pytest.raises(ProjectResetError, match="unsafe reset target"):
        plan_project_reset(tmp_path, project="Crown_of_Ash", targets=(target,))


def test_reset_plan_rejects_overlapping_targets(tmp_path: Path) -> None:
    _project(tmp_path)

    with pytest.raises(ProjectResetError, match="overlap"):
        plan_project_reset(
            tmp_path,
            project="Crown_of_Ash",
            targets=("runs", "runs/old-run"),
        )


def test_reset_plan_is_an_exact_hash_only_inventory(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "candidates").mkdir()
    (project / "candidates" / "candidate.yml").write_text(
        "status: old\n", encoding="utf-8"
    )

    plan = plan_project_reset(
        tmp_path,
        project="Crown_of_Ash",
        targets=("runs", "candidates"),
        plan_id="reset-001",
        now="2026-07-21T16:00:00Z",
    )

    entries = {item["path"]: item for item in plan["entries"]}
    assert set(entries) == {
        "candidates",
        "candidates/candidate.yml",
        "runs",
        "runs/old-run",
        "runs/old-run/fiction_draft.md",
    }
    assert entries["runs/old-run/fiction_draft.md"] == {
        "path": "runs/old-run/fiction_draft.md",
        "kind": "file",
        "sha256": hashlib.sha256(b"legacy prose\n").hexdigest(),
        "status": "present",
        "deletion_result": "pending",
    }
    assert entries["runs"]["kind"] == "directory"
    assert entries["runs"]["sha256"] is None
    assert plan["schema_version"] == 1
    assert plan["plan_id"] == "reset-001"
    assert plan["project"] == "Crown_of_Ash"
    assert plan["targets"] == ["candidates", "runs"]
    assert plan["status"] == "preview"
    assert plan["entry_count"] == 5
    assert len(plan["inventory_sha256"]) == 64
    assert "legacy prose" not in str(plan)


def test_reset_apply_fails_closed_when_preview_inventory_drifted(tmp_path: Path) -> None:
    project = _project(tmp_path)
    (project / "candidates").mkdir()
    candidate = project / "candidates" / "candidate.yml"
    candidate.write_text("status: old\n", encoding="utf-8")
    plan = plan_project_reset(
        tmp_path,
        project="Crown_of_Ash",
        targets=("runs", "candidates"),
        plan_id="reset-001",
    )
    candidate.write_text("status: changed-after-preview\n", encoding="utf-8")

    with pytest.raises(ProjectResetError, match="inventory changed"):
        apply_project_reset(
            tmp_path,
            plan=plan,
            confirm_project="Crown_of_Ash",
        )

    assert candidate.is_file()
    assert (project / "runs" / "old-run" / "fiction_draft.md").is_file()


def test_reset_apply_deletes_exact_preview_and_recreates_empty_runtime_roots(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    (project / "candidates").mkdir()
    (project / "candidates" / "candidate.yml").write_text(
        "status: old\n", encoding="utf-8"
    )
    plan = plan_project_reset(
        tmp_path,
        project="Crown_of_Ash",
        targets=("runs", "candidates"),
        plan_id="reset-001",
        now="2026-07-21T16:00:00Z",
    )

    result = apply_project_reset(
        tmp_path,
        plan=plan,
        confirm_project="Crown_of_Ash",
        now="2026-07-21T16:05:00Z",
    )

    assert result["status"] == "applied"
    assert result["applied_at"] == "2026-07-21T16:05:00Z"
    assert {item["path"] for item in result["entries"]} == {
        item["path"] for item in plan["entries"]
    }
    assert all(
        item["deletion_result"] in {"deleted", "not_applicable"}
        for item in result["entries"]
    )
    assert list((project / "runs").iterdir()) == []
    assert list((project / "candidates").iterdir()) == []


def test_reset_apply_exposes_hash_only_partial_result_when_deletion_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _project(tmp_path)
    plan = plan_project_reset(
        tmp_path,
        project="Crown_of_Ash",
        targets=("runs",),
        plan_id="reset-001",
    )
    original_rmdir = Path.rmdir

    def fail_old_run(path: Path) -> None:
        if path.name == "old-run":
            raise PermissionError("simulated deletion failure")
        original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", fail_old_run)

    with pytest.raises(ProjectResetApplyError) as raised:
        apply_project_reset(
            tmp_path,
            plan=plan,
            confirm_project="Crown_of_Ash",
        )

    result = raised.value.result
    entries = {item["path"]: item for item in result["entries"]}
    assert result["status"] == "failed_partial"
    assert entries["runs/old-run/fiction_draft.md"]["deletion_result"] == "deleted"
    assert entries["runs/old-run"]["deletion_result"] == "failed:PermissionError"
    assert "legacy prose" not in str(result)
    assert not (project / "runs" / "old-run" / "fiction_draft.md").exists()


def test_reset_apply_reinitializes_declared_state_contract_files(tmp_path: Path) -> None:
    project = _project(tmp_path)
    brain = project / "project_brain"
    brain.mkdir()
    old_files = {
        "task_index.yml": "tasks:\n  - old\n",
        "project_artifact_index.yml": "artifacts:\n  - old\n",
        "PROJECT_HANDOFF.md": "old handoff with prose\n",
        "project_brain/project_fact_snapshot.yml": "facts:\n  - old\n",
        "project_brain/revision_log.jsonl": '{"old": true}\n',
        "project_brain/project_state_contract.yml": "candidate_only: false\n",
    }
    for relative, content in old_files.items():
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    plan = plan_project_reset(
        tmp_path,
        project="Crown_of_Ash",
        targets=tuple(old_files),
        plan_id="reset-001",
    )

    apply_project_reset(
        tmp_path,
        plan=plan,
        confirm_project="Crown_of_Ash",
    )

    task_index = pytest.importorskip("yaml").safe_load(
        (project / "task_index.yml").read_text(encoding="utf-8")
    )
    snapshot = pytest.importorskip("yaml").safe_load(
        (brain / "project_fact_snapshot.yml").read_text(encoding="utf-8")
    )
    contract = pytest.importorskip("yaml").safe_load(
        (brain / "project_state_contract.yml").read_text(encoding="utf-8")
    )
    assert task_index["tasks"] == []
    assert snapshot == {
        "schema_version": 1,
        "project": "Crown_of_Ash",
        "reset_plan_id": "reset-001",
        "facts": [],
        "source_hashes": {},
        "conflicts": [],
    }
    assert contract["candidate_only"] is True
    assert contract["production_promotion_allowed"] is False
    assert contract["formal_fact_roots"] == ["production", "project_brain"]
    assert (brain / "revision_log.jsonl").read_text(encoding="utf-8") == ""
    assert "old" not in (project / "PROJECT_HANDOFF.md").read_text(encoding="utf-8")


def test_project_reset_cli_plan_writes_exact_manifest(tmp_path: Path) -> None:
    _project(tmp_path)
    app = typer.Typer()
    register_project_reset_commands(app, tmp_path, Console(file=io.StringIO()))
    manifest = tmp_path / "reset-preview.yml"

    result = CliRunner().invoke(
        app,
        [
            "project-reset",
            "plan",
            "--project",
            "Crown_of_Ash",
            "--plan-id",
            "reset-001",
            "--target",
            "runs",
            "--manifest",
            str(manifest),
        ],
    )

    assert result.exit_code == 0, result.output
    written = pytest.importorskip("yaml").safe_load(manifest.read_text(encoding="utf-8"))
    assert written["status"] == "preview"
    assert written["targets"] == ["runs"]
    assert written["entries"]


def test_project_reset_cli_apply_requires_execute_and_updates_manifest(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = typer.Typer()
    register_project_reset_commands(app, tmp_path, Console(file=io.StringIO()))
    manifest = tmp_path / "reset-preview.yml"
    runner = CliRunner()
    planned = runner.invoke(
        app,
        [
            "project-reset",
            "plan",
            "--project",
            "Crown_of_Ash",
            "--plan-id",
            "reset-001",
            "--target",
            "runs",
            "--manifest",
            str(manifest),
        ],
    )
    assert planned.exit_code == 0, planned.output

    refused = runner.invoke(
        app,
        [
            "project-reset",
            "apply",
            "--manifest",
            str(manifest),
            "--confirm-project",
            "Crown_of_Ash",
        ],
    )
    assert refused.exit_code != 0
    assert (project / "runs" / "old-run" / "fiction_draft.md").is_file()

    applied = runner.invoke(
        app,
        [
            "project-reset",
            "apply",
            "--manifest",
            str(manifest),
            "--confirm-project",
            "Crown_of_Ash",
            "--execute",
        ],
    )
    assert applied.exit_code == 0, applied.output
    result = pytest.importorskip("yaml").safe_load(manifest.read_text(encoding="utf-8"))
    assert result["status"] == "applied"
    assert list((project / "runs").iterdir()) == []


def test_project_reset_cli_is_registered_in_agentlab() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "agentlab.sh"), "project-reset", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "apply" in result.stdout
    assert "plan" in result.stdout
