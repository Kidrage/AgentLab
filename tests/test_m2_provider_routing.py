"""Tests for capability provider routing."""

from agent_runtime.capability_broker.broker_registry import BrokerRegistry
from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport
from agent_runtime.capability_broker.provider_trust import ProviderTrustPolicy
from agent_runtime.capability_broker.provider_routing import route_capability

def test_route_capability():
    registry = BrokerRegistry()
    trust_policy = ProviderTrustPolicy()

    # 1. Register a worker local skill for code_review
    passport = CapabilityProviderPassport(
        provider_id="claude_local_skill_code_review",
        provider_type="worker_local_skill",
        source="discovered",
        canonical_capabilities=["code_review"],
        risk_level="low",
        trust_level="provisional"
    )
    registry.register_passport(passport)

    # 2. Route code_review
    provider, decision = route_capability("code_review", registry, trust_policy)

    assert provider is not None
    assert provider.provider_id == "claude_local_skill_code_review"
    assert decision["status"] == "success"

    # 3. Route unknown capability
    provider_none, decision_fail = route_capability("unknown_cap", registry, trust_policy)
    assert provider_none is None
    assert decision_fail["status"] == "failed"
