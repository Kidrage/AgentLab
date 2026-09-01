from __future__ import annotations

import hashlib
import shutil
import threading
import warnings
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import agent_runtime.project_ops.result_export as result_export_module
from agent_runtime.project_artifact_steward import apply_archive_protocol, build_artifact_intent
from agent_runtime.project_ops.cli import app
from agent_runtime.project_ops.result_export import export_project_results
from agent_runtime.task_runtime_v2 import TaskRuntime
from task_runtime_v2_support import execute_role_with_output


runner = CliRunner()


def _write_candidate(
    root: Path,
    *,
    project: str = "DemoProject",
    task_id: str = "task-demo-001",
    artifact_id: str = "story_blueprint",
    content: str = "# Candidate blueprint\n",
) -> tuple[Path, str]:
    task_root = root / "projects" / project / "runtime" / "tasks" / task_id
    runtime = TaskRuntime(root, project=project)
    runtime.create_task(
        task_id=task_id,
        title="Produce one reviewable project result",
        user_goal=f"Produce {artifact_id} as one governed candidate.",
        idempotency_key=f"create-{task_id}",
    )
    runtime.create_work_item(
        task_id,
        job_id="job-main",
        work_item_id="result",
        kind="artifact",
        title="Produce result",
        idempotency_key=f"work-{task_id}",
    )
    execute_role_with_output(
        runtime,
        root,
        task_id=task_id,
        work_item_id="result",
        attempt_id="attempt-supervisor-001",
        role="Supervisor",
        output={"result": content},
        project=project,
    )
    staging = task_root / "artifacts" / "staging" / f"{artifact_id}.md"
    staging.parent.mkdir(parents=True)
    staging.write_text(content, encoding="utf-8")
    recorded = runtime.record_artifact_version(
        task_id,
        artifact_id=artifact_id,
        version_id="pv-demo",
        attempt_id="attempt-supervisor-001",
        path=staging,
        media_type="text/markdown",
        idempotency_key=f"artifact-{task_id}",
    )
    item = recorded["artifacts"]["pv-demo"]
    payload = task_root / item["path"]
    digest = str(item["sha256"])
    return payload, digest


def test_export_project_results_materializes_candidate_without_promoting(tmp_path: Path) -> None:
    source, digest = _write_candidate(tmp_path)

    result = export_project_results(
        tmp_path,
        project="DemoProject",
        task_id="task-demo-001",
    )

    exported = (
        tmp_path
        / "outputs"
        / "DemoProject"
        / "candidates"
        / "task-demo-001"
        / f"{digest}.md"
    )
    assert exported.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert result["status"] == "pass"
    assert result["production_modified"] is False
    assert result["exported_count"] == 1

    manifest = yaml.safe_load(
        (tmp_path / "outputs" / "DemoProject" / "manifest.yml").read_text(encoding="utf-8")
    )
    assert manifest["authority"] == "inspection_projection_only"
    assert manifest["candidates"][0]["sha256"] == digest
    assert manifest["candidates"][0]["lifecycle"] == "candidate"
    assert manifest["task_summaries"] == [{
        "task_id": "task-demo-001",
        "task_status": "created",
        "work_item_counts": {"ready": 1},
        "attempt_count": 1,
        "last_event_sequence": 6,
    }]
    assert not (tmp_path / "projects" / "DemoProject" / "production").exists()


def test_export_project_results_includes_formal_project_production(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "DemoProject"
    task_id = "task-production-001"
    run_dir = project_root / "runs" / task_id
    candidate = run_dir / "artifacts" / "山河有约.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("# 山河有约\n", encoding="utf-8")
    intent = build_artifact_intent(tmp_path, "DemoProject", task_id)
    (run_dir / "workflow_plan.yml").write_text(
        yaml.safe_dump(
            {
                "project": "DemoProject",
                "task_id": task_id,
                "artifact_intent": intent,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "artifact_promotion_plan.yml").write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "project": "DemoProject",
                "task_id": task_id,
                "promotions": [
                    {
                        "artifact_id": "shanhe_manuscript",
                        "source_run_artifact": "artifacts/山河有约.md",
                        "production_path": "production/artifacts/山河有约.md",
                        "action": "create",
                    }
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    receipt = apply_archive_protocol(tmp_path, "DemoProject", task_id)
    assert receipt["status"] == "completed", receipt.get("errors")
    production = project_root / "production" / "artifacts" / "山河有约.md"
    production_digest = hashlib.sha256(production.read_bytes()).hexdigest()
    automatically_exported = (
        tmp_path
        / "outputs"
        / "DemoProject"
        / "current"
        / "artifacts"
        / f"{production_digest}.md"
    )
    assert automatically_exported.read_text(encoding="utf-8") == "# 山河有约\n"

    result = export_project_results(tmp_path, project="DemoProject")

    exported = (
        tmp_path
        / "outputs"
        / "DemoProject"
        / "current"
        / "artifacts"
        / f"{production_digest}.md"
    )
    assert exported.read_text(encoding="utf-8") == "# 山河有约\n"
    assert result["exported_count"] == 1
    manifest = yaml.safe_load(
        (tmp_path / "outputs" / "DemoProject" / "manifest.yml").read_text(encoding="utf-8")
    )
    assert manifest["current"] == [
        {
            "artifact_id": "shanhe_manuscript",
            "lifecycle": "production",
            "sha256": production_digest,
            "size_bytes": len("# 山河有约\n".encode()),
            "source_path": "projects/DemoProject/production/artifacts/山河有约.md",
            "export_path": f"current/artifacts/{production_digest}.md",
        }
    ]

    index_path = project_root / "project_artifact_index.yml"
    index = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    index["artifacts"][0]["current_version"] = "forged-version-not-in-receipt"
    index_path.write_text(
        yaml.safe_dump(index, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="receipt does not bind"):
        export_project_results(tmp_path, project="DemoProject")

    index["artifacts"][0].pop("current_version")
    index_path.write_text(
        yaml.safe_dump(index, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    receipt_path = run_dir / "archive_receipt.yml"
    archived_receipt = yaml.safe_load(receipt_path.read_text(encoding="utf-8"))
    archived_receipt["promotions_applied"][0].pop("version")
    receipt_path.write_text(
        yaml.safe_dump(archived_receipt, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing its version"):
        export_project_results(tmp_path, project="DemoProject")


def test_export_project_results_excludes_unindexed_production_files(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "DemoProject"
    policy = project_root / "production" / "outbound_context_policy.yml"
    policy.parent.mkdir(parents=True)
    policy.write_text("candidate_only: true\n", encoding="utf-8")

    result = export_project_results(tmp_path, project="DemoProject")

    assert result["exported_count"] == 0
    assert not (tmp_path / "outputs" / "DemoProject" / "current" / policy.name).exists()


def test_project_result_export_removes_only_stale_files_from_its_prior_manifest(tmp_path: Path) -> None:
    _source, digest = _write_candidate(tmp_path, artifact_id="old_result", content="old result\n")
    export_project_results(tmp_path, project="DemoProject", task_id="task-demo-001")
    stale = (
        tmp_path
        / "outputs"
        / "DemoProject"
        / "candidates"
        / "task-demo-001"
        / f"{digest}.md"
    )
    assert stale.exists()
    unrelated = tmp_path / "outputs" / "DemoProject" / "operator-note.txt"
    unrelated.write_text("preserve me", encoding="utf-8")

    TaskRuntime(tmp_path, project="DemoProject").change_artifact_disposition(
        "task-demo-001",
        version_id="pv-demo",
        disposition="superseded",
        reason_code="replaced",
        feedback_digest="0" * 64,
        idempotency_key="supersede-old-result",
    )
    export_project_results(tmp_path, project="DemoProject", task_id="task-demo-001")

    assert not stale.exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve me"


def test_project_results_export_cli_reports_the_project_output_folder(tmp_path: Path) -> None:
    _write_candidate(tmp_path)

    result = runner.invoke(
        app,
        [
            "project-results-export",
            "--project",
            "DemoProject",
            "--task",
            "task-demo-001",
            "--root",
            str(tmp_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(result.output)
    assert payload["status"] == "pass"
    assert payload["output_root"] == str(tmp_path / "outputs" / "DemoProject")


def test_project_result_export_keeps_results_from_every_project_task(tmp_path: Path) -> None:
    _write_candidate(
        tmp_path,
        task_id="task-a",
        artifact_id="outline",
        content="outline\n",
    )
    export_project_results(tmp_path, project="DemoProject", task_id="task-a")
    _write_candidate(
        tmp_path,
        task_id="task-b",
        artifact_id="character_bible",
        content="characters\n",
    )

    export_project_results(tmp_path, project="DemoProject", task_id="task-b")

    manifest = yaml.safe_load(
        (tmp_path / "outputs" / "DemoProject" / "manifest.yml").read_text(encoding="utf-8")
    )
    assert {item["task_id"] for item in manifest["candidates"]} == {"task-a", "task-b"}
    assert {item["task_id"] for item in manifest["task_summaries"]} == {"task-a", "task-b"}


def test_recording_an_artifact_automatically_refreshes_project_results(tmp_path: Path) -> None:
    _source, digest = _write_candidate(tmp_path)

    exported = (
        tmp_path
        / "outputs"
        / "DemoProject"
        / "candidates"
        / "task-demo-001"
        / f"{digest}.md"
    )
    assert exported.is_file()
    manifest = yaml.safe_load(
        (tmp_path / "outputs" / "DemoProject" / "manifest.yml").read_text(encoding="utf-8")
    )
    assert manifest["candidates"][0]["version_id"] == "pv-demo"


def test_candidate_export_handles_the_maximum_legal_artifact_identifier(
    tmp_path: Path,
) -> None:
    artifact_id = "a" * 128
    _source, digest = _write_candidate(tmp_path, artifact_id=artifact_id)

    exported = (
        tmp_path
        / "outputs"
        / "DemoProject"
        / "candidates"
        / "task-demo-001"
        / f"{digest}.md"
    )
    assert exported.is_file()
    assert len(exported.name.encode("utf-8")) < 255


def test_production_export_bounds_long_multibyte_source_names() -> None:
    digest = "f" * 64
    source = Path("artifacts") / f"{'山' * 80}.md"

    relative = result_export_module._content_addressed_relative(source, digest)

    assert relative == Path("artifacts") / f"{digest}.md"
    assert len(relative.name.encode("utf-8")) < 255
    assert result_export_module._safe_export_suffix(f".{('x' * 100)}") == ".bin"


def test_projection_refresh_failure_never_changes_ledger_success_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_projection(*args, **kwargs):
        raise ValueError("injected projection failure")

    monkeypatch.setattr(result_export_module, "export_project_results", fail_projection)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _write_candidate(tmp_path)

    projection = TaskRuntime(tmp_path, project="DemoProject").load_task("task-demo-001")
    assert "pv-demo" in projection["artifacts"]


def test_project_result_export_rebuilds_candidates_from_ledger_not_projection(
    tmp_path: Path,
) -> None:
    source, digest = _write_candidate(tmp_path)
    runtime = TaskRuntime(tmp_path, project="DemoProject")
    runtime.change_artifact_disposition(
        "task-demo-001",
        version_id="pv-demo",
        disposition="superseded",
        reason_code="replaced",
        feedback_digest="0" * 64,
        idempotency_key="supersede-before-forgery",
    )
    projection = (
        tmp_path
        / "projects"
        / "DemoProject"
        / "runtime"
        / "tasks"
        / "task-demo-001"
        / "projections"
        / "artifact_index.yml"
    )
    projection.write_text(
        yaml.safe_dump(
            {
                "pv-demo": {
                    "artifact_id": "story_blueprint",
                    "version_id": "pv-demo",
                    "path": source.relative_to(projection.parents[1]).as_posix(),
                    "media_type": "text/markdown",
                    "size_bytes": source.stat().st_size,
                    "sha256": digest,
                    "disposition": "eligible",
                    "selection_eligible": True,
                }
            }
        ),
        encoding="utf-8",
    )

    result = export_project_results(
        tmp_path,
        project="DemoProject",
        task_id="task-demo-001",
    )

    assert result["exported_count"] == 0
    manifest = yaml.safe_load(
        (tmp_path / "outputs" / "DemoProject" / "manifest.yml").read_text(encoding="utf-8")
    )
    assert manifest["candidates"] == []


def test_project_result_export_rejects_ungoverned_current_production(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "DemoProject"
    production = project_root / "production" / "draft.md"
    production.parent.mkdir(parents=True)
    production.write_text("not stewarded\n", encoding="utf-8")
    (project_root / "project_artifact_index.yml").write_text(
        yaml.safe_dump(
            {
                "artifacts": [
                    {
                        "artifact_id": "draft",
                        "status": "current",
                        "production_path": "production/draft.md",
                        "production_sha256": hashlib.sha256(production.read_bytes()).hexdigest(),
                        "source_task": "task-missing",
                        "source_run_artifact": "artifacts/missing.md",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="governance|source|promotion receipt|version"):
        export_project_results(tmp_path, project="DemoProject")


def test_stale_cleanup_failure_keeps_a_recoverable_cleanup_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _source_a, digest_a = _write_candidate(
        tmp_path,
        task_id="task-a",
        artifact_id="a_result",
    )
    _source_z, digest_z = _write_candidate(
        tmp_path,
        task_id="task-z",
        artifact_id="z_result",
    )
    output_root = tmp_path / "outputs" / "DemoProject"
    manifest_path = output_root / "manifest.yml"
    stale_a = (
        output_root
        / "candidates"
        / "task-a"
        / f"{digest_a}.md"
    )
    stale_z = (
        output_root
        / "candidates"
        / "task-z"
        / f"{digest_z}.md"
    )
    stale_z.unlink()
    stale_z.mkdir()
    monkeypatch.setattr(TaskRuntime, "_refresh_project_results", lambda *args, **kwargs: None)
    runtime = TaskRuntime(tmp_path, project="DemoProject")
    for task_id, idempotency_key in (
        ("task-a", "supersede-a"),
        ("task-z", "supersede-z"),
    ):
        runtime.change_artifact_disposition(
            task_id,
            version_id="pv-demo",
            disposition="superseded",
            reason_code="replaced",
            feedback_digest="0" * 64,
            idempotency_key=idempotency_key,
        )

    with pytest.raises(ValueError, match="not a regular file"):
        export_project_results(tmp_path, project="DemoProject")
    assert not stale_a.exists()
    interrupted = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert interrupted["pending_cleanup"] == [
        f"candidates/task-a/{digest_a}.md",
        f"candidates/task-z/{digest_z}.md",
    ]

    with pytest.raises(ValueError, match="not a regular file"):
        export_project_results(tmp_path, project="DemoProject")
    retried = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert retried["pending_cleanup"] == interrupted["pending_cleanup"]


def test_materialization_intent_precedes_any_new_result_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TaskRuntime, "_refresh_project_results", lambda *args, **kwargs: None)
    _source, digest = _write_candidate(tmp_path)
    real_write = result_export_module._atomic_write_bytes

    def fail_first_manifest(root: Path, path: Path, payload: bytes) -> None:
        if path.name == "manifest.yml":
            raise OSError("injected journal failure")
        real_write(root, path, payload)

    monkeypatch.setattr(result_export_module, "_atomic_write_bytes", fail_first_manifest)
    with pytest.raises(OSError, match="journal failure"):
        export_project_results(tmp_path, project="DemoProject")
    candidate = (
        tmp_path
        / "outputs"
        / "DemoProject"
        / "candidates"
        / "task-demo-001"
        / f"{digest}.md"
    )
    assert not candidate.exists()


def test_project_export_lock_prevents_an_old_snapshot_overwriting_newer_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_candidate(tmp_path, task_id="task-a", artifact_id="outline")
    monkeypatch.setattr(TaskRuntime, "_refresh_project_results", lambda *args, **kwargs: None)
    first_snapshot = threading.Event()
    release_first = threading.Event()
    second_snapshot = threading.Event()
    real_rebuild = result_export_module._rebuilt_task_projections
    calls = 0
    calls_lock = threading.Lock()

    def pausing_rebuild(*args, **kwargs):
        nonlocal calls
        result = real_rebuild(*args, **kwargs)
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_snapshot.set()
            assert release_first.wait(timeout=5)
        else:
            second_snapshot.set()
        return result

    monkeypatch.setattr(result_export_module, "_rebuilt_task_projections", pausing_rebuild)
    failures: list[BaseException] = []

    def run_export() -> None:
        try:
            export_project_results(tmp_path, project="DemoProject")
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)

    first = threading.Thread(target=run_export)
    first.start()
    assert first_snapshot.wait(timeout=5)
    _write_candidate(tmp_path, task_id="task-b", artifact_id="characters")
    second = threading.Thread(target=run_export)
    second.start()
    assert not second_snapshot.wait(timeout=0.2)
    release_first.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not failures
    assert second_snapshot.is_set()
    manifest = yaml.safe_load(
        (tmp_path / "outputs" / "DemoProject" / "manifest.yml").read_text(encoding="utf-8")
    )
    assert {item["task_id"] for item in manifest["candidates"]} == {"task-a", "task-b"}


def test_project_result_export_rejects_identifier_traversal(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()

    with pytest.raises(ValueError, match="invalid project"):
        export_project_results(tmp_path, project="../escaped")

    assert not (tmp_path.parent / "escaped").exists()


def test_project_result_export_rejects_source_hash_drift(tmp_path: Path) -> None:
    source, _digest = _write_candidate(tmp_path)
    source.write_text("drifted", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        export_project_results(tmp_path, project="DemoProject", task_id="task-demo-001")


def test_project_result_export_rejects_symlinked_output_project(tmp_path: Path) -> None:
    _write_candidate(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    outputs = tmp_path / "outputs"
    shutil.rmtree(outputs / "DemoProject")
    (outputs / "DemoProject").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        export_project_results(tmp_path, project="DemoProject", task_id="task-demo-001")

    assert not list(outside.iterdir())


def test_project_result_export_rejects_symlinked_task_ancestry(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "DemoProject"
    project_root.mkdir(parents=True)
    outside_runtime = tmp_path / "outside-runtime"
    outside_task = outside_runtime / "tasks" / "task-demo-001"
    payload = outside_task / "artifacts" / "versions" / "pv-demo" / "payload.md"
    payload.parent.mkdir(parents=True)
    payload.write_text("outside", encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    projection = outside_task / "projections" / "artifact_index.yml"
    projection.parent.mkdir(parents=True)
    projection.write_text(
        yaml.safe_dump(
            {
                "pv-demo": {
                    "artifact_id": "story_blueprint",
                    "version_id": "pv-demo",
                    "path": "artifacts/versions/pv-demo/payload.md",
                    "media_type": "text/markdown",
                    "size_bytes": payload.stat().st_size,
                    "sha256": digest,
                    "disposition": "eligible",
                    "selection_eligible": True,
                }
            }
        ),
        encoding="utf-8",
    )
    (project_root / "runtime").symlink_to(outside_runtime, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        export_project_results(tmp_path, project="DemoProject", task_id="task-demo-001")

    assert not (tmp_path / "outputs" / "DemoProject" / "candidates").exists()
