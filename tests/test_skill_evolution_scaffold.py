from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

import cost_tracker
from skill_evolution import (
    build_skill_adoption_request,
    build_trace_skill_candidate,
    ensure_skill_registry,
    estimate_skill_learning_cost,
    load_skill_requests,
    summarize_skill_system,
    write_skill_adoption_request,
    write_trace_skill_candidate,
)


def _write_pricing(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "config" / "model_pricing.yml").write_text(
        yaml.safe_dump({
            "version": 1,
            "currency": "USD",
            "models": {
                "deepseek/deepseek-v4-pro": {
                    "input_per_1m": 1.0,
                    "output_per_1m": 2.0,
                },
            },
        }, sort_keys=False),
        encoding="utf-8",
    )
    cost_tracker._PRICE_CACHE = None
    cost_tracker._PRICE_ROOT = None


def test_skill_learning_cost_uses_model_pricing(tmp_path: Path) -> None:
    _write_pricing(tmp_path)

    preview = estimate_skill_learning_cost(
        tmp_path,
        provider="deepseek",
        model="deepseek-v4-pro",
        validation_runs=2,
    )

    assert preview["input_tokens"] > 0
    assert preview["output_tokens"] > 0
    assert preview["total_tokens"] == preview["input_tokens"] + preview["output_tokens"]
    assert preview["estimated_cost"] is not None
    assert preview["exact_cost_available"] is True


def test_skill_request_queue_is_pending_only(tmp_path: Path) -> None:
    _write_pricing(tmp_path)
    ensure_skill_registry(tmp_path)

    request = build_skill_adoption_request(
        tmp_path,
        project="Demo",
        skill_name="production-code-review",
        source="https://example.invalid/skills/review",
        purpose="Improve review gates.",
        source_type="github",
        applies_to=["repo_audit", "test_repair"],
    )
    path = write_skill_adoption_request(tmp_path, request)

    assert path.exists()
    loaded = load_skill_requests(tmp_path, "Demo")
    assert len(loaded) == 1
    assert loaded[0]["status"] == "pending_user_approval"
    assert loaded[0]["risk"]["requires_network"] is True

    summary = summarize_skill_system(tmp_path, "Demo")
    assert summary["skill_count"] == 0
    assert summary["pending_request_count"] == 1


def test_trace_skill_candidate_writes_under_task_run(tmp_path: Path) -> None:
    candidate = build_trace_skill_candidate(
        project="Demo",
        task_id="task_001",
        name="agentlab-lifecycle-debugging",
        evidence=["progress.yml was stale"],
        trigger="When lifecycle status and progress disagree.",
        steps=["Read progress.yml", "Read lifecycle.yml", "Reconcile terminal state"],
        estimated_future_value="high",
    )
    path = write_trace_skill_candidate(tmp_path, candidate)

    assert path.exists()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["status"] == "pending_review"
    assert data["created_from_task"] == "task_001"
    assert "Reconcile terminal state" in data["proposed_skill"]["steps"]
