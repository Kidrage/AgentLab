from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import cost_tracker
from post_task_learning import (
    approve_skill_candidate,
    list_skill_candidates,
    reject_skill_candidate,
    run_learning_review,
)
from skill_evolution import load_skill_registry, load_skill_requests, validate_skill_registry
from task_events import append_task_event


def _run_dir(root: Path, task_id: str = "task_0001_learning") -> Path:
    run_dir = root / "projects" / "Demo" / "runs" / task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_pricing(root: Path) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "currency": "USD",
            "models": {
                "deepseek/deepseek-v4-pro": {"input_per_1m": 1.0, "output_per_1m": 2.0},
            },
        }, sort_keys=False),
        encoding="utf-8",
    )
    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None


def test_completed_task_creates_learning_review(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)

    review = run_learning_review(tmp_path, "Demo", "task_0001_learning")

    assert (run_dir / "learning_review.yml").exists()
    assert review["status"] == "reviewed_no_candidate"
    assert review["candidate_count"] == 0


def test_blocked_event_creates_skill_candidate(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    append_task_event(run_dir, "NODE_BLOCKED", status="FAILED_RECOVERABLE", severity="BLOCKED", message="Blocked by approval.")

    review = run_learning_review(tmp_path, "Demo", "task_0001_learning")

    assert review["candidate_count"] == 1
    candidates = list_skill_candidates(tmp_path, "Demo", "task_0001_learning")
    assert candidates[0]["pattern_type"] == "blocked_event"


def test_validation_failure_creates_skill_candidate(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    (run_dir / "07_validation_report.md").write_text("Result: required validation command failed.\n", encoding="utf-8")

    review = run_learning_review(tmp_path, "Demo", "task_0001_learning")

    assert review["candidate_count"] == 1
    assert list_skill_candidates(tmp_path, "Demo", "task_0001_learning")[0]["pattern_type"] == "validation_failure"


def test_no_reusable_pattern_creates_review_but_no_candidate(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    append_task_event(run_dir, "TASK_COMPLETED", status="COMPLETED_PASS", severity="COMPLETED", message="Done.")

    review = run_learning_review(tmp_path, "Demo", "task_0001_learning")

    assert (run_dir / "learning_review.yml").exists()
    assert review["patterns"] == []
    assert list_skill_candidates(tmp_path, "Demo", "task_0001_learning") == []


def test_candidate_approval_creates_self_learned_skill_request(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    run_dir = _run_dir(tmp_path)
    append_task_event(run_dir, "NODE_BLOCKED", status="FAILED_RECOVERABLE", severity="BLOCKED", message="Blocked by approval.")
    run_learning_review(tmp_path, "Demo", "task_0001_learning")
    candidate = list_skill_candidates(tmp_path, "Demo", "task_0001_learning")[0]

    approved = approve_skill_candidate(tmp_path, "Demo", "task_0001_learning", candidate["id"])

    assert approved["status"] == "approved"
    requests = load_skill_requests(tmp_path, "Demo")
    assert len(requests) == 1
    assert requests[0]["source"]["type"] == "self_learned"
    assert requests[0]["created_from_candidate"] == candidate["id"]
    registry = load_skill_registry(tmp_path)
    entry = registry["skills"][0]
    assert entry["source_project"] == "Demo"
    assert entry["source_task_id"] == "task_0001_learning"
    assert entry["approval_status"] == "approved"
    assert entry["safety_review_status"] == "passed"
    assert entry["triggers"]
    assert entry["evidence_paths"]
    assert (tmp_path / entry["path"]).exists()


def test_candidate_reject_does_not_update_registry(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    append_task_event(run_dir, "NODE_BLOCKED", status="FAILED_RECOVERABLE", severity="BLOCKED", message="Blocked by approval.")
    run_learning_review(tmp_path, "Demo", "task_0001_learning")
    candidate = list_skill_candidates(tmp_path, "Demo", "task_0001_learning")[0]

    rejected = reject_skill_candidate(tmp_path, "Demo", "task_0001_learning", candidate["id"], "Too narrow.")

    assert rejected["status"] == "rejected"
    assert load_skill_registry(tmp_path)["skills"] == []


def test_registry_validate_detects_required_field_duplicate_and_bad_path(tmp_path: Path) -> None:
    (tmp_path / "skills").mkdir(parents=True)
    (tmp_path / "skills" / "registry.yml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "skills": [
                    {
                        "skill_id": "trace_to_skill/demo",
                        "category": "trace_to_skill",
                        "source_project": "Demo",
                        "source_task_id": "task_0001_learning",
                        "approval_status": "approved",
                        "safety_review_status": "passed",
                        "generalization_notes": "ok",
                        "triggers": ["When blocked."],
                        "evidence_paths": ["task_events.jsonl"],
                        "path": ".agents/skills/missing/SKILL.md",
                    },
                    {"skill_id": "trace_to_skill/demo"},
                ],
                "retired_skills": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = validate_skill_registry(tmp_path)

    assert result["valid"] is False
    assert any("duplicate skill_id" in item for item in result["errors"])
    assert any("missing required field" in item for item in result["errors"])
    assert any("path does not exist" in item for item in result["errors"])
