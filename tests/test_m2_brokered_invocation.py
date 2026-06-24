"""Tests for brokered MCP invocations."""

import pytest
from agent_runtime.capability_broker.provider_passport import CapabilityProviderPassport
from agent_runtime.capability_broker.capability_provider import CapabilityProvider
from agent_runtime.capability_broker.brokered_invocation import invoke_brokered_provider

def test_invoke_brokered_provider():
    provider = CapabilityProvider(CapabilityProviderPassport(
        provider_id="test_mcp",
        provider_type="agentlab_brokered_mcp",
        source="discovered",
        invocation_mode="brokered_mcp",
        risk_level="medium"
    ))

    result = invoke_brokered_provider(provider, "filesystem_read", {"path": "/tmp"})
    assert result["success"] is True
    assert "evidence" in result
    assert result["evidence"]["provider_id"] == "test_mcp"

    # Critical risk should raise error
    provider_critical = CapabilityProvider(CapabilityProviderPassport(
        provider_id="test_mcp_crit",
        provider_type="agentlab_brokered_mcp",
        source="discovered",
        invocation_mode="brokered_mcp",
        risk_level="critical"
    ))
    with pytest.raises(PermissionError):
        invoke_brokered_provider(provider_critical, "filesystem_write", {"path": "/tmp"})
