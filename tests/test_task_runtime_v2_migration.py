from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import yaml
import pytest

from agent_runtime.task_runtime_v2 import LedgerIntegrityError
from agent_runtime.task_runtime_v2.migration import (
    LegacyRunMigrator,
    MigrationPlanChanged,
)


def test_legacy_migration_is_hash_gated_idempotent_and_non_destructive(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task-old"
    run_dir.mkdir(parents=True)
    state_path = run_dir / "state.yml"
    state_path.write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "task_id": "task-old",
                "status": "completed",
                "last_event": "Legacy delivery completed",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (run_dir / "user_request.md").write_text("Deliver the legacy result.\n", encoding="utf-8")
    original_hash = hashlib.sha256(state_path.read_bytes()).hexdigest()
    migrator = LegacyRunMigrator(tmp_path, project="Demo")

    plan = migrator.plan()

    assert plan["schema_version"] == "task-runtime-legacy-migration-plan/v3"
    assert plan["source_count"] == 1
    assert plan["sources"][0]["state_sha256"] == original_hash
    assert not (tmp_path / "projects" / "Demo" / "runtime" / "tasks").exists()
    assert migrator.runtime.list_tasks(include_legacy=True) == [
        {
            "task_id": "task-old",
            "status": "completed",
            "title": "task-old",
            "storage": "legacy-read-only",
        }
    ]

    applied = migrator.apply(expected_plan_hash=plan["plan_hash"])
    repeated = migrator.apply(expected_plan_hash=plan["plan_hash"])

    assert applied["imported"] == ["task-old"]
    assert repeated["already_imported"] == ["task-old"]
    projection = migrator.runtime.load_task("task-old")
    assert projection["task"]["status"] == "completed"
    assert projection["task"]["legacy_source"]["state_sha256"] == original_hash
    snapshot_root = (
        tmp_path
        / "projects"
        / "Demo"
        / "runtime"
        / "provenance"
        / "legacy"
        / "task-old"
    )
    assert projection["task"]["legacy_source"]["state_path"] == (
        "projects/Demo/runtime/provenance/legacy/task-old/state.yml"
    )
    assert projection["task"]["legacy_source"]["request_path"] == (
        "projects/Demo/runtime/provenance/legacy/task-old/user_request.md"
    )
    assert hashlib.sha256((snapshot_root / "state.yml").read_bytes()).hexdigest() == original_hash
    assert (snapshot_root / "user_request.md").read_text(encoding="utf-8") == (
        "Deliver the legacy result.\n"
    )
    listed = migrator.runtime.list_tasks(include_legacy=True)
    assert len(listed) == 1
    assert listed[0]["storage"] == "v2"
    assert state_path.is_file()
    assert hashlib.sha256(state_path.read_bytes()).hexdigest() == original_hash

    (run_dir / "user_request.md").unlink()
    state_path.unlink()
    run_dir.rmdir()
    assert migrator.runtime.doctor_project()["ok"] is True

    (snapshot_root / "state.yml").write_bytes(
        (snapshot_root / "state.yml").read_bytes() + b"\ncorrupt\n"
    )
    doctor = migrator.runtime.doctor_project()
    assert doctor["ok"] is False
    assert doctor["tasks"]["task-old"]["failures"] == [
        "legacy state provenance SHA256 mismatch"
    ]


def test_legacy_migration_rejects_cross_project_state(tmp_path: Path) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task-wrong-project"
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(
        yaml.safe_dump(
            {"project": "AnotherProject", "task_id": "task-wrong-project"}
        ),
        encoding="utf-8",
    )

    with pytest.raises(LedgerIntegrityError, match="project mismatch"):
        LegacyRunMigrator(tmp_path, project="Demo").plan()


def test_legacy_migration_rejects_symlinked_provenance_parent(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task-old"
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "task_id": "task-old",
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )
    migrator = LegacyRunMigrator(tmp_path, project="Demo")
    plan = migrator.plan()
    outside = tmp_path / "outside-provenance"
    outside.mkdir()
    aliased_parent = migrator.provenance_root / "task-old"
    aliased_parent.parent.mkdir(parents=True)
    aliased_parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MigrationPlanChanged, match="symlink component"):
        migrator.apply(expected_plan_hash=plan["plan_hash"])

    assert not (outside / "state.yml").exists()


def test_runtime_doctor_rejects_internal_provenance_directory_alias(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "projects" / "Demo" / "runs" / "task-old"
    run_dir.mkdir(parents=True)
    (run_dir / "state.yml").write_text(
        yaml.safe_dump(
            {
                "project": "Demo",
                "task_id": "task-old",
                "status": "completed",
            }
        ),
        encoding="utf-8",
    )
    migrator = LegacyRunMigrator(tmp_path, project="Demo")
    plan = migrator.plan()
    migrator.apply(expected_plan_hash=plan["plan_hash"])
    snapshot_root = migrator.provenance_root / "task-old"
    internal_target = migrator.provenance_root / "stored-task-old"
    shutil.move(snapshot_root, internal_target)
    snapshot_root.symlink_to(internal_target, target_is_directory=True)

    doctor = migrator.runtime.doctor_project()

    assert doctor["ok"] is False
    assert doctor["tasks"]["task-old"]["failures"] == [
        "legacy state provenance path contains a symlink component"
    ]
