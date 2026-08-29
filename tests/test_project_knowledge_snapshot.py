from __future__ import annotations

from pathlib import Path
import hashlib
import os
import re
import subprocess

import yaml

from agent_runtime.artifact_digest import artifact_sha256
from agent_runtime.knowledge_system import (
    build_knowledge_base,
    write_project_knowledge_snapshot,
)
from agent_runtime.project_truth import ChangeSet, FactChange, ProjectTruthStore


def test_project_narrative_snapshot_exposes_only_production_and_project_brain(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config" / "knowledge_system.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        yaml.safe_dump(
            {
                "mode": "assist",
                "auto_memory": "propose_only",
                "indexing": {"project_allowlist": ["Crown_of_Ash"]},
                "retrieval": {"required_channels": ["keyword"]},
            }
        ),
        encoding="utf-8",
    )
    project = tmp_path / "projects" / "Crown_of_Ash"
    canonical = project / "production" / "canonical"
    canonical.mkdir(parents=True)
    fact = canonical / "facts.yml"
    fact.write_text("fact: ASH-CANON\n", encoding="utf-8")
    brain = project / "project_brain" / "fact_distillation.yml"
    brain.parent.mkdir(parents=True)
    brain.write_text("fact: DISTILLED-ASH\n", encoding="utf-8")
    old_run = project / "runs" / "old" / "fiction_draft.md"
    old_run.parent.mkdir(parents=True)
    old_run.write_text("OLD-PROSE-MUST-NOT-BE-WRITER-RAG\n", encoding="utf-8")
    artifact_index = project / "project_artifact_index.yml"
    artifact_index.write_text(
        yaml.safe_dump(
            {
                "artifacts": [
                    {
                        "artifact_id": "canonical_blueprint",
                        "status": "current",
                        "production_path": "production/canonical",
                        "production_sha256": artifact_sha256(canonical),
                        "evidence_only": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    build = build_knowledge_base(tmp_path, projects=["Crown_of_Ash"])

    snapshot = write_project_knowledge_snapshot(
        tmp_path,
        project="Crown_of_Ash",
        build_receipt=build,
    )

    expected = {
        "projects/Crown_of_Ash/production/canonical/facts.yml",
        "projects/Crown_of_Ash/project_brain/fact_distillation.yml",
    }
    assert snapshot["namespace"] == "project.Crown_of_Ash"
    assert snapshot["formal_fact_roots"] == ["production", "project_brain"]
    assert set(snapshot["indexed_paths"]) == expected
    assert all("runs/" not in item for item in snapshot["indexed_paths"])
    assert snapshot["indexed_source_hashes"][
        "projects/Crown_of_Ash/production/canonical/facts.yml"
    ] == hashlib.sha256(fact.read_bytes()).hexdigest()
    written = yaml.safe_load(
        (project / "project_brain" / "knowledge_index_snapshot.yml").read_text(
            encoding="utf-8"
        )
    )
    assert written == snapshot


def test_knowledge_build_cli_exposes_project_snapshot_seal() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [str(root / "agentlab.sh"), "knowledge", "build", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **{
                key: value
                for key, value in os.environ.items()
                if key not in {"FORCE_COLOR", "CLICOLOR_FORCE"}
            },
            "COLUMNS": "180",
            "NO_COLOR": "1",
        },
    )

    assert result.returncode == 0, result.stderr
    stdout = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout)
    assert "--seal-project-snapshot" in stdout


def test_enforced_project_snapshot_binds_only_current_canonical_truth(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config" / "knowledge_system.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        yaml.safe_dump(
            {
                "mode": "assist",
                "auto_memory": "propose_only",
                "indexing": {"project_allowlist": ["Crown_of_Ash"]},
                "retrieval": {"required_channels": ["keyword"]},
            }
        ),
        encoding="utf-8",
    )
    project = tmp_path / "projects" / "Crown_of_Ash"
    project.mkdir(parents=True)
    (project / "project.yml").write_text(
        yaml.safe_dump(
            {
                "project_id": "Crown_of_Ash",
                "features": {
                    "project_truth_mode": "enforced",
                    "enable_project_agents": True,
                },
                "workspace": {"isolation": "required"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    truth = ProjectTruthStore(project)
    initial = truth.initialize("Crown_of_Ash")
    truth.commit(
        ChangeSet(
            project_id="Crown_of_Ash",
            expected_snapshot_id=initial.current_snapshot_id,
            actor_id="user",
            idempotency_key="policy-v3",
            facts=(
                FactChange(
                    key="narrative.character_content_policy_revision",
                    value=3,
                    owner="style_guardian",
                ),
            ),
        )
    )
    build = build_knowledge_base(tmp_path, projects=["Crown_of_Ash"])

    snapshot = write_project_knowledge_snapshot(
        tmp_path,
        project="Crown_of_Ash",
        build_receipt=build,
    )

    assert snapshot["formal_fact_roots"] == ["canonical_truth"]
    assert snapshot["indexed_paths"] == sorted(
        [
            "projects/Crown_of_Ash/project_truth.yml",
            (
                "projects/Crown_of_Ash/.agentlab/truth/snapshots/"
                f"{truth.current().snapshot_id}.yml"
            ),
        ]
    )
