from pathlib import Path

from agent_runtime.routing.fallback_policy import WorkerFallbackPolicy


ROOT = Path(__file__).resolve().parents[1]


def test_coder_fallback_order() -> None:
    policy = WorkerFallbackPolicy(ROOT / "config" / "worker_fallback_policy.yml")
    assert policy.fallbacks("Coder", "claude_code")[:2] == ["codex", "aider"]
