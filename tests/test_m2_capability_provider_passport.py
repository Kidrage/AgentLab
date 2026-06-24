"""Tests for CapabilityProviderPassport serialization and validation."""

from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport

def test_provider_passport_serialization():
    passport_dict = {
        "provider_id": "test_provider",
        "provider_type": "agentlab_owned_tool",
        "source": "agentlab_owned",
        "canonical_capabilities": ["read_only_repo_search"],
        "transparency": "transparent",
        "invocation_mode": "direct",
        "permissions": {
            "filesystem_read": "scoped",
            "filesystem_write": "none",
            "shell": "limited",
            "network": "no",
            "cloud_upload": "no"
        },
        "risk_level": "low",
        "cost_model": {
            "known": True,
            "attribution": "provider_level",
            "estimated_usd": 0.0,
            "estimated_tokens": 0
        },
        "verification": {
            "probe_available": True,
            "audition_required": False
        },
        "trust_level": "trusted"
    }

    passport = CapabilityProviderPassport.from_dict(passport_dict)
    assert passport.provider_id == "test_provider"
    assert passport.permissions.filesystem_read == "scoped"
    assert passport.cost_model.known is True
    assert passport.verification.probe_available is True
    assert passport.trust_level == "trusted"

    serialized = passport.to_dict()
    assert serialized["provider_id"] == "test_provider"
    assert serialized["permissions"]["filesystem_read"] == "scoped"
