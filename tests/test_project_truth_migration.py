from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
import pytest

from agent_runtime.project_truth import (
    ProjectTruthMigrator,
    ProjectTruthStore,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_migration_plan_surfaces_conflicting_legacy_facts(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Crown"
    brain = project_root / "project_brain"
    brain.mkdir(parents=True)
    (brain / "brief.yml").write_text("total_word_count: 120000\n", encoding="utf-8")
    (brain / "scope.yml").write_text("total_word_count: 150000\n", encoding="utf-8")

    plan = ProjectTruthMigrator(project_root).plan("Crown")

    assert plan["status"] == "requires_human_resolution"
    conflict = next(
        item
        for item in plan["potential_fact_conflicts"]
        if item["leaf_key"] == "total_word_count"
    )
    assert set(conflict["values"]) == {"120000", "150000"}
    assert plan["activation_ready"] is False


def test_explicit_migration_manifest_selects_one_truth_and_activates_enforcement(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Crown"
    brain = project_root / "project_brain"
    brain.mkdir(parents=True)
    project_file = project_root / "project.yml"
    project_file.write_text(
        yaml.safe_dump(
            {
                "project_id": "Crown",
                "features": {
                    "project_truth_mode": "legacy",
                    "enable_project_agents": False,
                },
                "workspace": {"isolation": "required"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    characters = brain / "characters.yml"
    characters.write_text("aria:\n  age: 27\n", encoding="utf-8")

    result = ProjectTruthMigrator(project_root).apply(
        {
            "schema_version": "project-truth-migration/v1",
            "project_id": "Crown",
            "idempotency_key": "crown-truth-migration-v1",
            "expected_source_hashes": {
                "project_brain/characters.yml": _sha(characters),
            },
            "facts": [
                {
                    "key": "novel.total_word_count",
                    "value": 150_000,
                    "owner": "project.editorial",
                    "evidence_refs": ["project_brain/characters.yml"],
                }
            ],
            "resources": [
                {
                    "key": "characters.current",
                    "source_path": "project_brain/characters.yml",
                    "media_type": "application/yaml",
                }
            ],
            "enable_project_agents": False,
        }
    )

    truth = ProjectTruthStore(project_root)
    assert result["status"] == "migrated"
    assert truth.current().facts["novel.total_word_count"].value == 150_000
    assert truth.current().resources["characters.current"].content == {
        "aria": {"age": 27}
    }
    project = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    assert project["features"] == {
        "project_truth_mode": "enforced",
        "enable_project_agents": False,
    }


def test_migration_rejects_unbound_fact_evidence(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "Crown"
    project_root.mkdir(parents=True)
    (project_root / "project.yml").write_text(
        "project_id: Crown\nfeatures:\n  project_truth_mode: legacy\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="hash-bound evidence"):
        ProjectTruthMigrator(project_root).apply(
            {
                "schema_version": "project-truth-migration/v1",
                "project_id": "Crown",
                "idempotency_key": "unsafe",
                "expected_source_hashes": {},
                "facts": [
                    {
                        "key": "novel.total_word_count",
                        "value": 150_000,
                        "owner": "project.editorial",
                    }
                ],
            }
        )
