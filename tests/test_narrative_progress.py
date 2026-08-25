from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from agent_runtime.narrative.progress import build_narrative_progress
from agent_runtime.narrative.blueprint_bootstrap import create_blueprint_task
from agent_runtime.narrative.state_store import (
    NarrativeStateIntegrityError,
    NarrativeStateStore,
    narrative_payload_sha256,
)


ROOT = Path(__file__).resolve().parents[1]


def test_progress_reports_precanon_blueprint_task_evidence(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    for name in (
        "production_packs.yml",
        "task_input_tiers.yml",
        "agent_model_profiles.yml",
        "production_role_profiles.yml",
        "narrative_author_team.yml",
        "agent_registry.yml",
    ):
        shutil.copy2(ROOT / "config" / name, config / name)
    brief = tmp_path / "brief.yml"
    brief.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-blueprint-request/v1",
                "project": "ShanHeYouJia",
                "title": "山河有约",
                "genres": ["wuxia"],
                "target_total_chapters": 600,
                "target_han_characters": 2_800_000,
                "creative_seed": {
                    "premise": "Rise from nothing.",
                    "ending": "One True Immortal.",
                },
                "content_boundary": {
                    "all_romance_participants_adults": True,
                    "contextual_consent": True,
                    "exit_right": True,
                    "explicitness": "non_graphic",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    create_blueprint_task(
        tmp_path,
        project="ShanHeYouJia",
        task_id="task-blueprint-progress",
        request_path=brief,
    )

    report = build_narrative_progress(tmp_path, project="ShanHeYouJia")

    assert report["target_total_chapters"] == 600
    assert report["blueprint_statuses"] == [
        {
            "task_id": "task-blueprint-progress",
            "title": "Generate blueprint: 山河有约",
            "user_goal": (
                "Create a governed 600-chapter longform blueprint for《山河有约》 "
                "without promoting candidate artifacts before human acceptance."
            ),
            "goal_fingerprint": report["blueprint_statuses"][0]["goal_fingerprint"],
            "task_status": "created",
            "target_total_chapters": 600,
            "source_creative_brief_sha256": report["blueprint_statuses"][0][
                "source_creative_brief_sha256"
            ],
            "work_item_status_counts": {"pending": 12, "ready": 1},
            "ready_work_items": ["authorial_director"],
            "succeeded_attempt_count": 0,
            "failed_attempts": [],
            "candidate_artifacts": [],
            "artifact_hash_collisions": [],
            "automated_quality_issues": ["story_blueprint_candidate_missing"],
            "automated_acceptance_ready": False,
            "protocol_gates": [],
        }
    ]


def _commit_chapter(
    store: NarrativeStateStore,
    project_root: Path,
    *,
    chapter: int,
) -> None:
    artifact_sha256 = f"{chapter:064x}"
    brief_sha256 = hashlib.sha256(f"brief-{chapter}".encode()).hexdigest()
    projection_sha256 = hashlib.sha256(f"projection-{chapter}".encode()).hexdigest()
    verification_sha256 = hashlib.sha256(f"verification-{chapter}".encode()).hexdigest()
    state_delta: dict = {}
    binding = {
        "artifact_sha256": artifact_sha256,
        "brief_sha256": brief_sha256,
        "source_projection_sha256": projection_sha256,
        "verification_result_sha256": verification_sha256,
        "state_delta_sha256": narrative_payload_sha256(state_delta),
    }
    receipts = project_root / "receipts"
    receipts.mkdir(exist_ok=True)
    seal_path = receipts / f"seal-{chapter:03d}.yml"
    delta_path = receipts / f"delta-{chapter:03d}.yml"
    seal_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "narrative-seal-receipt/v1",
                "issuer": "AgentLab.Supervisor",
                "attempt_id": f"supervisor-{chapter}",
                "evidence_binding_id": f"chapter-{chapter}",
                "status": "accepted",
                **binding,
            }
        ),
        encoding="utf-8",
    )
    delta_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "delta-verification-receipt/v1",
                "issuer": "AgentLab.DeltaVerifier",
                "attempt_id": f"delta-{chapter}",
                "evidence_binding_id": f"chapter-{chapter}",
                "status": "pass",
                "source_projection_sha256": projection_sha256,
                "verification_result_sha256": verification_sha256,
            }
        ),
        encoding="utf-8",
    )
    before = store.read()
    store.commit(
        {
            "schema_version": "verified-chapter-commit/v1",
            "project": "ShanHeYouJia",
            "chapter": chapter,
            "artifact_sha256": artifact_sha256,
            "brief_sha256": brief_sha256,
            "source_projection_sha256": projection_sha256,
            "state_delta_sha256": binding["state_delta_sha256"],
            "seal": {
                "status": "accepted",
                "attempt_id": f"supervisor-{chapter}",
                "evidence_binding_id": f"chapter-{chapter}",
                "receipt_path": seal_path.relative_to(project_root).as_posix(),
                "receipt_sha256": hashlib.sha256(seal_path.read_bytes()).hexdigest(),
                **binding,
            },
            "delta_verification": {
                "status": "pass",
                "attempt_id": f"delta-{chapter}",
                "evidence_binding_id": f"chapter-{chapter}",
                "receipt_path": delta_path.relative_to(project_root).as_posix(),
                "receipt_sha256": hashlib.sha256(delta_path.read_bytes()).hexdigest(),
                "source_projection_sha256": projection_sha256,
                "verification_result_sha256": verification_sha256,
            },
            "previous_state_sha256": before["state_sha256"],
            "state_delta": state_delta,
        }
    )


def test_progress_is_derived_from_verified_commit_events_not_mutable_snapshot_fields(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "ShanHeYouJia"
    source = project_root / "production" / "story_blueprint.yml"
    source.parent.mkdir(parents=True)
    source.write_text("project: ShanHeYouJia\n", encoding="utf-8")
    store = NarrativeStateStore(
        project_root / "project_brain",
        project="ShanHeYouJia",
    )
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "ShanHeYouJia",
            "precedence": ["accepted_blueprint"],
            "sources": [
                {
                    "path": source.relative_to(project_root).as_posix(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
            "base_state": {
                "series": {"planned_total_chapters": 600},
                "chapters": {
                    "1": {"artifact_sha256": "f" * 64},
                    "3": {"artifact_sha256": "e" * 64},
                },
            },
        }
    )

    report = build_narrative_progress(
        tmp_path,
        project="ShanHeYouJia",
        verify_ledger=True,
    )

    assert report["status"] == "pass"
    assert report["target_total_chapters"] == 600
    assert report["accepted_chapters"] == []
    assert report["highest_contiguous_accepted"] == 0
    assert report["next_production_chapter"] == 1
    assert report["event_ledger"]["verified"] is True


def test_progress_reports_only_the_highest_contiguous_accepted_prefix(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "projects" / "ShanHeYouJia"
    source = project_root / "production" / "story_blueprint.yml"
    source.parent.mkdir(parents=True)
    source.write_text("project: ShanHeYouJia\n", encoding="utf-8")
    store = NarrativeStateStore(project_root / "project_brain", project="ShanHeYouJia")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "ShanHeYouJia",
            "precedence": ["accepted_blueprint"],
            "sources": [
                {
                    "path": source.relative_to(project_root).as_posix(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
            "base_state": {"series": {"planned_total_chapters": 600}},
        }
    )
    _commit_chapter(store, project_root, chapter=1)
    _commit_chapter(store, project_root, chapter=3)

    report = build_narrative_progress(tmp_path, project="ShanHeYouJia")

    assert report["accepted_chapters"] == [1, 3]
    assert report["accepted_count"] == 2
    assert report["highest_contiguous_accepted"] == 1
    assert report["accepted_gaps"] == [2]
    assert report["next_production_chapter"] == 2
    by_chapter = {item["chapter"]: item for item in report["chapter_statuses"]}
    assert by_chapter[3]["accepted"] is True
    assert len(by_chapter[3]["acceptance_evidence"]["event_hash"]) == 64


def test_progress_verification_rejects_a_tampered_event_chain(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "ShanHeYouJia"
    source = project_root / "production" / "story_blueprint.yml"
    source.parent.mkdir(parents=True)
    source.write_text("project: ShanHeYouJia\n", encoding="utf-8")
    store = NarrativeStateStore(project_root / "project_brain", project="ShanHeYouJia")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "ShanHeYouJia",
            "precedence": ["accepted_blueprint"],
            "sources": [
                {
                    "path": source.relative_to(project_root).as_posix(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
            "base_state": {},
        }
    )
    event = json.loads(store.events_path.read_text(encoding="utf-8"))
    event["payload"]["precedence"] = ["tampered"]
    store.events_path.write_text(json.dumps(event) + "\n", encoding="utf-8")

    with pytest.raises(NarrativeStateIntegrityError):
        build_narrative_progress(tmp_path, project="ShanHeYouJia")


def test_progress_cli_renders_the_verified_projection(tmp_path: Path) -> None:
    (tmp_path / "agentlab.sh").touch()
    (tmp_path / "agent_runtime").mkdir()
    project_root = tmp_path / "projects" / "ShanHeYouJia"
    source = project_root / "production" / "story_blueprint.yml"
    source.parent.mkdir(parents=True)
    source.write_text("project: ShanHeYouJia\n", encoding="utf-8")
    store = NarrativeStateStore(project_root / "project_brain", project="ShanHeYouJia")
    store.bootstrap(
        {
            "schema_version": "narrative-bootstrap/v1",
            "project": "ShanHeYouJia",
            "precedence": ["accepted_blueprint"],
            "sources": [
                {
                    "path": source.relative_to(project_root).as_posix(),
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                }
            ],
            "base_state": {"series": {"planned_total_chapters": 600}},
        }
    )

    result = subprocess.run(
        [
            str(ROOT / "agentlab.sh"),
            "narrative",
            "progress",
            "--project",
            "ShanHeYouJia",
            "--verify-ledger",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "AGENTLAB_ROOT": str(tmp_path),
            "NO_COLOR": "1",
            "COLUMNS": "240",
        },
    )

    assert result.returncode == 0, result.stderr
    report = yaml.safe_load(result.stdout)
    assert report["schema_version"] == "narrative-progress-report/v1"
    assert report["event_ledger"]["verified"] is True
