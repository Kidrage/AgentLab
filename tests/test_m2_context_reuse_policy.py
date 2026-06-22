"""Tests for context reuse policies and budgets."""

from agent_runtime.execution_economy.context_reuse_policy import ContextReusePolicy

def test_context_reuse_policy():
    policy = ContextReusePolicy()
    
    budget_default = policy.get_budget_for_worker("some_unknown_worker")
    assert budget_default.max_raw_tokens == 16000
    assert "task_contract" in budget_default.required_assets
    assert "full_chat_history" in budget_default.excluded_assets
    
    budget_claude = policy.get_budget_for_worker("claude_code")
    assert budget_claude.max_raw_tokens == 32000
    assert "repo_map" in budget_claude.required_assets
