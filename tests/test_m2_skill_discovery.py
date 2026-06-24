"""Tests for local skill discovery."""

from agent_runtime.capability_broker.skill_discovery import discover_worker_skills

def test_discover_worker_skills():
    discovered = discover_worker_skills("claude_code", safe=True)
    assert len(discovered) == 1
    assert discovered[0].provider_id == "claude_local_skill_code_review"
    assert "code_review" in discovered[0].canonical_capabilities
    assert discovered[0].trust_level == "provisional"

    discovered_unsafe = discover_worker_skills("claude_code", safe=False)
    assert discovered_unsafe[0].trust_level == "untrusted"
