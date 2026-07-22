from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
import pytest

from agent_runtime.task_runtime_v2 import LedgerIntegrityError
from agent_runtime.task_runtime_v2.migration import LegacyRunMigrator


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

    assert plan["schema_version"] == "task-runtime-legacy-migration-plan/v2"
    assert plan["source_count"] == 1
    assert plan["sources"][0]["state_sha256"] == original_hash
    assert not (tmp_path / "projects" / "Demo" / "runtime" / "tasks").exists()
    assert migrator.runtime.list_tasks() == [
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
    listed = migrator.runtime.list_tasks()
    assert len(listed) == 1
    assert listed[0]["storage"] == "v2"
    assert state_path.is_file()
    assert hashlib.sha256(state_path.read_bytes()).hexdigest() == original_hash


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
