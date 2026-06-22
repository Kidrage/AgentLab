"""Tests for local MCP server discovery."""

from agent_runtime.capability_broker.mcp_discovery import discover_worker_mcps

def test_discover_worker_mcps():
    discovered = discover_worker_mcps("claude_code", safe=True)
    assert len(discovered) == 1
    assert discovered[0].provider_id == "claude_local_mcp_fs"
    assert "filesystem_read" in discovered[0].canonical_capabilities
    assert discovered[0].trust_level == "provisional"
