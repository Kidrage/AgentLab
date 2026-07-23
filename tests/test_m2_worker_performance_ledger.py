from __future__ import annotations

from pathlib import Path
import pytest

from agent_runtime.workers.performance_ledger import PerformanceLedger
from agent_runtime.workers.performance_ledger import default_performance_ledger_path


def test_default_ledger_path_is_runtime_state(tmp_path: Path) -> None:
    assert default_performance_ledger_path(tmp_path) == (
        tmp_path / ".agentlab" / "runtime" / "worker_performance_ledger.yml"
    )


def test_performance_ledger_lifecycle(tmp_path: Path) -> None:
    ledger_file = tmp_path / "worker_performance_ledger.yml"
    ledger = PerformanceLedger(ledger_file)

    # Empty at start
    assert len(ledger.performances) == 0

    # Update performance
    ledger.update_performance(
        worker_id="claude_code",
        role="Coder",
        score=0.91,
        cost_score=0.35,
        safety_score=0.68,
        suite="standard",
        verdict="pass",
        timestamp="2026-06-22T12:00:00",
        is_success=True
    )

    # Verify memory state
    perf = ledger.get_worker_performance("claude_code")
    assert perf is not None
    assert perf["role_scores"]["coder"] == 0.91
    assert perf["cost_score"] == 0.35
    assert perf["safety_score"] == 0.68
    assert perf["historical_runs"]["total"] == 1
    assert perf["historical_runs"]["success"] == 1

    # Verify persistence
    ledger2 = PerformanceLedger(ledger_file)
    perf2 = ledger2.get_worker_performance("claude_code")
    assert perf2 is not None
    assert perf2["role_scores"]["coder"] == 0.91


def test_get_best_worker_for_role(tmp_path: Path) -> None:
    ledger_file = tmp_path / "worker_performance_ledger.yml"
    ledger = PerformanceLedger(ledger_file)

    # Set up some performance metrics
    ledger.update_performance("claude_code", "Coder", 0.91, 0.3, 0.4, "standard", "pass", "t1", True)
    ledger.update_performance("aider", "Coder", 0.75, 0.3, 0.4, "standard", "pass", "t2", True)

    best = ledger.get_best_worker_for_role("Coder", ["claude_code", "aider"])
    assert best == "claude_code"

    # For a role without scores, falls back to first compatible worker
    best_fallback = ledger.get_best_worker_for_role("Supervisor", ["qwen", "gemini"])
    assert best_fallback == "qwen"
