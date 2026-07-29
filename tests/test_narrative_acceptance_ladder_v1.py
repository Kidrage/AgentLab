from __future__ import annotations

from pathlib import Path
import hashlib

import yaml

from agent_runtime.narrative.acceptance_ladder import (
    build_narrative_acceptance_status,
)

ROOT = Path(__file__).resolve().parents[1]


def test_acceptance_ladder_fails_closed_without_stage_evidence(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Crown_of_Ash"
    project_root.mkdir(parents=True)

    result = build_narrative_acceptance_status(
        ROOT,
        project="Crown_of_Ash",
        project_root=project_root,
        evidence_dir=project_root / "acceptance",
    )

    assert result["schema_version"] == "narrative-acceptance-status/v1"
    assert [stage["stage"] for stage in result["stages"]] == [
        "P0",
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
    ]
    assert all(stage["status"] == "missing" for stage in result["stages"])
    assert result["highest_completed_stage"] is None
    assert result["full_scale_production_ready"] is False
    assert result["claim_1980_chapter_capability_allowed"] is False


def test_acceptance_ladder_requires_complete_hash_verified_p5_metrics(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "Crown_of_Ash"
    evidence_dir = project_root / "acceptance"
    evidence_dir.mkdir(parents=True)
    artifact = project_root / "verified-evidence.yml"
    artifact.write_text("verified: true\n", encoding="utf-8")
    artifact_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    ladder = yaml.safe_load(
        (ROOT / "config" / "narrative_acceptance_ladder.yml").read_text(
            encoding="utf-8"
        )
    )
    metrics = {
        "hard_continuity_errors": 0,
        "planted_fact_and_promise_recall": 0.95,
        "state_and_retrieval_traceability": 1.0,
        "cross_project_knowledge_leaks": 0,
        "due_promise_resolution_rate": 1.0,
        "blind_preference_rate": 0.65,
        "consecutive_windows_without_core_regression": 2,
    }
    for stage_id, stage in ladder["stages"].items():
        receipt = {
            "schema_version": "narrative-acceptance-receipt/v1",
            "project": "Crown_of_Ash",
            "stage": stage_id,
            "status": "pass",
            "checks": {
                check_id: {"status": "pass"}
                for check_id in stage["required_checks"]
            },
            "artifact_bindings": [
                {
                    "path": "verified-evidence.yml",
                    "sha256": artifact_sha256,
                }
            ],
        }
        if stage_id == "P5":
            receipt["release_metrics"] = metrics
        (evidence_dir / f"{stage_id}.yml").write_text(
            yaml.safe_dump(receipt, sort_keys=False),
            encoding="utf-8",
        )

    accepted = build_narrative_acceptance_status(
        ROOT,
        project="Crown_of_Ash",
        project_root=project_root,
        evidence_dir=evidence_dir,
    )
    assert accepted["highest_completed_stage"] == "P5"
    assert accepted["release_metrics_pass"] is True
    assert accepted["claim_1980_chapter_capability_allowed"] is True

    artifact.write_text("verified: replaced\n", encoding="utf-8")
    rejected = build_narrative_acceptance_status(
        ROOT,
        project="Crown_of_Ash",
        project_root=project_root,
        evidence_dir=evidence_dir,
    )
    assert rejected["stages"][0]["status"] == "blocked"
    assert rejected["stages"][0]["issues"] == [
        "artifact_sha256_mismatch:verified-evidence.yml"
    ]
    assert rejected["claim_1980_chapter_capability_allowed"] is False
