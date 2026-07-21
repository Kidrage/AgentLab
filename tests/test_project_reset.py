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
    fact_distillation_issues,
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


def test_reset_plan_is_blocked_by_nonterminal_blocked_lock(tmp_path: Path) -> None:
    _project(tmp_path)
    locks = tmp_path / ".agents" / "locks"
    locks.mkdir(parents=True)
    (locks / "crown-blocked.lock").write_text(
        "agent: codex\nstatus: blocked\npaths:\n  - projects/Crown_of_Ash\n",
        encoding="utf-8",
    )

    with pytest.raises(ActiveProjectResetError, match="crown-blocked.lock"):
        plan_project_reset(tmp_path, project="Crown_of_Ash", targets=("runs",))


def test_reset_plan_is_blocked_by_absolute_project_lock_path(tmp_path: Path) -> None:
    project = _project(tmp_path)
    locks = tmp_path / ".agents" / "locks"
    locks.mkdir(parents=True)
    (locks / "crown-absolute.lock").write_text(
        pytest.importorskip("yaml").safe_dump(
            {
                "agent": "codex",
                "status": "blocked",
                "paths": [str(project)],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ActiveProjectResetError, match="crown-absolute.lock"):
        plan_project_reset(tmp_path, project="Crown_of_Ash", targets=("runs",))


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


def test_reset_preserves_hash_bound_metadata_only_fact_distillation(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project / "production" / "bible" / "canon.yml"
    source.parent.mkdir(parents=True)
    source.write_text("stable_id: character.kane\n", encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    old_brain = project / "project_brain"
    old_brain.mkdir()
    (old_brain / "old_memory.yml").write_text("legacy: true\n", encoding="utf-8")
    seed = project / "reset_manifests" / "fact_distillation.yml"
    seed.parent.mkdir()
    seed.write_text(
        pytest.importorskip("yaml").safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "legacy_prose_retained": False,
                "facts": [
                    {
                        "id": "fact.character.kane.identity",
                        "kind": "character_fact",
                        "value": {"character_ref": "character.kane"},
                        "source_hashes": [source_hash],
                        "conflict_status": "resolved",
                        "conflict_conclusion": "canonical identity retained",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    plan = plan_project_reset(
        tmp_path,
        project="Crown_of_Ash",
        targets=("production", "project_brain", "runs"),
        plan_id="reset-001",
        distillation_seed="reset_manifests/fact_distillation.yml",
    )

    assert plan["preserved_distillation"] == {
        "path": "reset_manifests/fact_distillation.yml",
        "sha256": hashlib.sha256(seed.read_bytes()).hexdigest(),
        "fact_count": 1,
        "status": "validated",
    }
    assert "canonical identity retained" not in str(plan)

    apply_project_reset(tmp_path, plan=plan, confirm_project="Crown_of_Ash")

    restored = pytest.importorskip("yaml").safe_load(
        (project / "project_brain" / "fact_distillation.yml").read_text(
            encoding="utf-8"
        )
    )
    snapshot = pytest.importorskip("yaml").safe_load(
        (project / "project_brain" / "project_fact_snapshot.yml").read_text(
            encoding="utf-8"
        )
    )
    assert restored["facts"][0]["id"] == "fact.character.kane.identity"
    assert snapshot["facts"] == restored["facts"]
    assert snapshot["source_hashes"] == {
        "fact.character.kane.identity": [source_hash]
    }
    assert not (project / "production").exists()
    assert not (project / "project_brain" / "old_memory.yml").exists()
    assert list((project / "runs").iterdir()) == []


def test_reset_apply_rejects_plan_with_preservation_binding_removed(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source = project / "production" / "facts.yml"
    source.parent.mkdir()
    source.write_text("fact: stable\n", encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    seed = project / "reset_manifests" / "fact_distillation.yml"
    seed.parent.mkdir()
    seed.write_text(
        pytest.importorskip("yaml").safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "legacy_prose_retained": False,
                "facts": [
                    {
                        "id": "fact.stable",
                        "kind": "world_fact",
                        "value": "stable",
                        "source_hashes": [source_hash],
                        "conflict_status": "resolved",
                        "conflict_conclusion": "retained",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    plan = plan_project_reset(
        tmp_path,
        project="Crown_of_Ash",
        targets=("production", "project_brain", "runs"),
        plan_id="reset-001",
        distillation_seed="reset_manifests/fact_distillation.yml",
    )
    plan.pop("preserved_distillation")

    with pytest.raises(ProjectResetError, match="plan binding digest|distillation"):
        apply_project_reset(tmp_path, plan=plan, confirm_project="Crown_of_Ash")

    assert source.is_file()


def test_reset_plan_rejects_distillation_seed_through_symlink(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = project / "production" / "facts.yml"
    source.parent.mkdir()
    source.write_text("fact: stable\n", encoding="utf-8")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    actual = project / "project_brain" / "seed.yml"
    actual.parent.mkdir()
    actual.write_text(
        pytest.importorskip("yaml").safe_dump(
            {
                "schema_version": 1,
                "status": "approved",
                "legacy_prose_retained": False,
                "facts": [
                    {
                        "id": "fact.stable",
                        "kind": "world_fact",
                        "value": "stable",
                        "source_hashes": [source_hash],
                        "conflict_status": "resolved",
                        "conflict_conclusion": "retained",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    seed = project / "reset_manifests" / "fact_distillation.yml"
    seed.parent.mkdir()
    seed.symlink_to(actual)

    with pytest.raises(ProjectResetError, match="symlink|surviving"):
        plan_project_reset(
            tmp_path,
            project="Crown_of_Ash",
            targets=("production", "project_brain", "runs"),
            distillation_seed="reset_manifests/fact_distillation.yml",
        )


def test_fact_distillation_rejects_nested_prose_and_malformed_schema() -> None:
    nested = {
        "schema_version": 1,
        "status": "approved",
        "legacy_prose_retained": False,
        "facts": [
            {
                "id": "fact.hidden",
                "kind": "world_fact",
                "value": {"raw_prose": "legacy paragraph\n" * 20},
                "source_hashes": ["a" * 64],
                "conflict_status": "resolved",
                "conflict_conclusion": "retained",
            }
        ],
    }
    assert any("forbidden_payload_key" in issue for issue in fact_distillation_issues(nested))

    malformed = {**nested, "schema_version": {"invalid": True}}
    malformed["facts"][0][3] = "mixed key"
    issues = fact_distillation_issues(malformed)
    assert "invalid_schema_version" in issues
    assert any("invalid_field_key" in issue for issue in issues)


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
