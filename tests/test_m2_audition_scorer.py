from __future__ import annotations

from agent_runtime.workers.audition_scorer import AuditionScorer


def test_scorer_success_case() -> None:
    # Test a cheap, fast, low-risk, successful worker
    scores = AuditionScorer.calculate_scores(
        worker_id="rg",
        role="RepoScout",
        is_success=True,
        cost_usd=0.0,
        latency_s=0.1,
        worker_risk="low"
    )
    
    assert scores["success_rate"] == 1.0
    assert scores["cost_score"] == 1.0
    assert scores["safety_score"] == 0.95
    assert scores["latency_score"] > 0.9
    assert scores["role_fit_score"] >= 0.9


def test_scorer_failure_case() -> None:
    # Test a failed worker run
    scores = AuditionScorer.calculate_scores(
        worker_id="claude_code",
        role="Coder",
        is_success=False,
        cost_usd=0.25,
        latency_s=5.0,
        worker_risk="high"
    )
    
    assert scores["success_rate"] == 0.0
    assert scores["cost_score"] == 0.3
    assert scores["safety_score"] == 0.40
    assert scores["role_fit_score"] < 0.5
