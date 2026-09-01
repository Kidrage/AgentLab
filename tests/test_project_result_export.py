from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agent_runtime.project_ops.cli import app
from agent_runtime.project_ops.result_export import export_project_results


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
    payload = task_root / "artifacts" / "versions" / "pv-demo" / "payload.md"
    payload.parent.mkdir(parents=True)
    payload.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    projection = {
        "pv-demo": {
            "artifact_id": artifact_id,
            "version_id": "pv-demo",
            "path": payload.relative_to(task_root).as_posix(),
            "media_type": "text/markdown",
            "size_bytes": payload.stat().st_size,
            "sha256": digest,
            "disposition": "eligible",
            "selection_eligible": True,
        }
    }
    projection_path = task_root / "projections" / "artifact_index.yml"
    projection_path.parent.mkdir(parents=True)
    projection_path.write_text(yaml.safe_dump(projection, sort_keys=False), encoding="utf-8")
    (task_root / "projections" / "progress.yml").write_text(
        yaml.safe_dump(
            {
                "task_id": task_id,
                "task_status": "running",
                "work_item_counts": {"accepted": 2, "ready": 1},
                "attempt_count": 3,
                "last_event_sequence": 12,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
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
        / f"story_blueprint--{digest[:12]}.md"
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
    assert manifest["task_summary"] == {
        "task_id": "task-demo-001",
        "task_status": "running",
        "work_item_counts": {"accepted": 2, "ready": 1},
        "attempt_count": 3,
        "last_event_sequence": 12,
    }
    assert not (tmp_path / "projects" / "DemoProject" / "production").exists()


def test_export_project_results_includes_formal_project_production(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "DemoProject"
    production = project_root / "production" / "manuscript" / "山河有约.md"
    production.parent.mkdir(parents=True)
    production.write_text("# 山河有约\n", encoding="utf-8")
    production_digest = hashlib.sha256(production.read_bytes()).hexdigest()
    (project_root / "project_artifact_index.yml").write_text(
        yaml.safe_dump(
            {
                "artifacts": [
                    {
                        "artifact_id": "shanhe_manuscript",
                        "status": "current",
                        "production_path": "production/manuscript/山河有约.md",
                        "production_sha256": production_digest,
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = export_project_results(tmp_path, project="DemoProject")

    exported = tmp_path / "outputs" / "DemoProject" / "current" / "manuscript" / "山河有约.md"
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
            "source_path": "projects/DemoProject/production/manuscript/山河有约.md",
            "export_path": "current/manuscript/山河有约.md",
        }
    ]


def test_export_project_results_excludes_unindexed_production_files(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "DemoProject"
    policy = project_root / "production" / "outbound_context_policy.yml"
    policy.parent.mkdir(parents=True)
    policy.write_text("candidate_only: true\n", encoding="utf-8")

    result = export_project_results(tmp_path, project="DemoProject")

    assert result["exported_count"] == 0
    assert not (tmp_path / "outputs" / "DemoProject" / "current" / policy.name).exists()


def test_project_result_export_removes_only_stale_files_from_its_prior_manifest(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "DemoProject"
    production = project_root / "production" / "manuscript" / "old.md"
    production.parent.mkdir(parents=True)
    production.write_text("old result\n", encoding="utf-8")
    digest = hashlib.sha256(production.read_bytes()).hexdigest()
    index = project_root / "project_artifact_index.yml"
    index.write_text(
        yaml.safe_dump(
            {
                "artifacts": [
                    {
                        "artifact_id": "old_result",
                        "status": "current",
                        "production_path": "production/manuscript/old.md",
                        "production_sha256": digest,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    export_project_results(tmp_path, project="DemoProject")
    stale = tmp_path / "outputs" / "DemoProject" / "current" / "manuscript" / "old.md"
    assert stale.exists()
    unrelated = tmp_path / "outputs" / "DemoProject" / "operator-note.txt"
    unrelated.write_text("preserve me", encoding="utf-8")

    index.write_text("artifacts: []\n", encoding="utf-8")
    export_project_results(tmp_path, project="DemoProject")

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
    outputs.mkdir()
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
