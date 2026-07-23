from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.run_retention import (
    archive_runs_from_plan,
    build_run_retention_plan,
    resolve_run_dir,
)


def _write_policy(root: Path) -> None:
    config = root / "config"
    config.mkdir()
    (config / "run_retention_policy.yml").write_text(
        yaml.safe_dump(
            {
                "archive_root": "archive/run_history",
                "protect_marker": ".agentlab_keep",
                "protect_statuses": ["new", "running", "paused"],
                "archive_name_patterns": ["*_mock_*", "task_probe_*"],
                "project_overrides": {
                    "Demo": {"protect_name_patterns": ["task_probe_canonical_*"]}
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_retention_plan_is_fail_closed_for_active_and_pinned_runs(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    runs = tmp_path / "projects" / "Demo" / "runs"
    (runs / "task_ch01_mock_old").mkdir(parents=True)
    active = runs / "task_probe_active"
    active.mkdir()
    (active / "state.yml").write_text("status: running\n", encoding="utf-8")
    (runs / "task_probe_canonical_v1").mkdir()
    (runs / "task_real_delivery").mkdir()

    plan = build_run_retention_plan(tmp_path, "Demo")

    assert [item["run_id"] for item in plan["candidates"]] == ["task_ch01_mock_old"]
    assert {item["protection_reason"] for item in plan["protected"]} == {
        "status:running",
        "pattern:task_probe_canonical_*",
    }
    assert plan["ignored_count"] == 1


def test_archive_moves_runs_and_writes_recovery_manifest(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task_ch01_mock_old"
    run_dir.mkdir(parents=True)
    (run_dir / "artifact.txt").write_text("evidence", encoding="utf-8")
    plan = build_run_retention_plan(tmp_path, "Demo")

    manifest = archive_runs_from_plan(tmp_path, plan, batch_id="batch-001")

    archived = (
        tmp_path
        / "projects"
        / "Demo"
        / "archive"
        / "run_history"
        / "batch-001"
        / "runs"
        / "task_ch01_mock_old"
    )
    assert manifest["status"] == "complete"
    assert manifest["entries"][0]["moved"] is True
    assert not run_dir.exists()
    assert (archived / "artifact.txt").read_text(encoding="utf-8") == "evidence"
    persisted = yaml.safe_load(
        archived.parent.parent.joinpath("archive_manifest.yml").read_text(encoding="utf-8")
    )
    assert persisted["status"] == "complete"


def test_resolve_run_dir_prefers_active_run_over_retained_evidence(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    active = tmp_path / "projects" / "Demo" / "runs" / "task_probe_same"
    archived = (
        tmp_path
        / "projects"
        / "Demo"
        / "archive"
        / "run_history"
        / "batch-001"
        / "runs"
        / "task_probe_same"
    )
    active.mkdir(parents=True)
    archived.mkdir(parents=True)

    assert resolve_run_dir(tmp_path, "Demo", "task_probe_same") == active


def test_resolve_run_dir_finds_retained_evidence_without_restoring_it(tmp_path: Path) -> None:
    _write_policy(tmp_path)
    archived = (
        tmp_path
        / "projects"
        / "Demo"
        / "archive"
        / "run_history"
        / "batch-001"
        / "runs"
        / "task_probe_archived"
    )
    archived.mkdir(parents=True)

    assert resolve_run_dir(tmp_path, "Demo", "task_probe_archived") == archived
    assert not (tmp_path / "projects" / "Demo" / "runs" / "task_probe_archived").exists()


def test_resolve_run_dir_returns_expected_active_path_when_missing(tmp_path: Path) -> None:
    _write_policy(tmp_path)

    expected = tmp_path / "projects" / "Demo" / "runs" / "task_missing"

    assert resolve_run_dir(tmp_path, "Demo", "task_missing") == expected
