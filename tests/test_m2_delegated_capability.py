"""Tests for delegated worker-local capability execution."""

from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport
from agent_runtime.capability_broker.capability_provider import CapabilityProvider
from agent_runtime.capability_broker.delegated_capability import invoke_delegated_capability

def test_invoke_delegated_capability():
    provider = CapabilityProvider(CapabilityProviderPassport(
        provider_id="claude_local_skill_code_review",
        provider_type="worker_local_skill",
        owner_worker="claude_code",
        source="discovered",
        invocation_mode="delegated_worker",
        risk_level="low",
        trust_level="provisional"
    ))

    result = invoke_delegated_capability(provider, "code_review", {"repo": "agentlab"})
    assert result["success"] is True
    assert "evidence" in result
    assert result["evidence"]["owner_worker"] == "claude_code"
