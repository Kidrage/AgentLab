"""Tests for provider trust evaluation policies."""

from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport
from agent_runtime.capability_broker.capability_provider import CapabilityProvider
from agent_runtime.capability_broker.provider_trust import ProviderTrustPolicy

def test_provider_trust_policy():
    policy = ProviderTrustPolicy()

    # 1. AgentLab owned is trusted
    p1 = CapabilityProvider(CapabilityProviderPassport(
        provider_id="rs", provider_type="agentlab_owned_tool", source="agentlab_owned", risk_level="low"
    ))
    assert policy.evaluate_trust(p1) == "trusted"

    # 2. Critical risk is disabled
    p2 = CapabilityProvider(CapabilityProviderPassport(
        provider_id="bad", provider_type="worker_local_skill", source="discovered", risk_level="critical"
    ))
    assert policy.evaluate_trust(p2) == "disabled"

    # 3. Discovered low risk is provisional
    p3 = CapabilityProvider(CapabilityProviderPassport(
        provider_id="ok", provider_type="worker_local_skill", source="discovered", risk_level="low"
    ))
    assert policy.evaluate_trust(p3) == "provisional"

    p4 = CapabilityProvider(CapabilityProviderPassport(
        provider_id="unsafe", provider_type="worker_local_skill", source="discovered", risk_level="high"
    ))
    assert policy.evaluate_trust(p4) == "provisional"

    # Generate trust report check
    report = policy.generate_trust_report([p1, p2, p3, p4])
    assert "Provider Trust Report" in report
    assert "rs" in report
    assert "bad" in report
