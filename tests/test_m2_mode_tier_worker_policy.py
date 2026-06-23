from pathlib import Path

from agent_runtime.routing.mode_tier_policy import ModeTierWorkerPolicy


ROOT = Path(__file__).resolve().parents[1]


def test_hybrid_prefers_deterministic_workers() -> None:
    policy = ModeTierWorkerPolicy(ROOT / "config" / "mode_tier_worker_policy.yml")
    assert policy.rank(["claude_code", "rg"], "RepoScout", "hybrid_local_company", "performance")[0] == "rg"
    assert policy.permits("claude_code", "high", "hybrid_local_company", "low")[0] is False
