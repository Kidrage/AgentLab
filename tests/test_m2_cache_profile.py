"""Tests for cache profile calculation."""

from agent_runtime.execution_economy.cache_profile import calculate_cache_profile

def test_calculate_cache_profile():
    profile = calculate_cache_profile("claude_code", ["git-hooks", "python-lint"], ["mcp-fs"])

    assert profile.stable_prefix_hash.startswith("sha256:")
    assert profile.skill_context_hash.startswith("sha256:")
    assert profile.mcp_manifest_hash.startswith("sha256:")
    assert profile.cache_confidence == "medium"

    profile_simple = calculate_cache_profile("rg")
    assert profile_simple.skill_context_hash is None
    assert profile_simple.cache_confidence == "high"
