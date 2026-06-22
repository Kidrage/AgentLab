"""MCP server discovery for local workers."""

from typing import List
from agent_runtime.capability_broker.provider_passport import (
    CapabilityProviderPassport, PassportPermissions, CostModel, VerificationModel
)

def discover_worker_mcps(worker_id: str, safe: bool = True) -> List[CapabilityProviderPassport]:
    """Discover local MCP servers exposed or used by a worker."""
    discovered = []
    
    if worker_id == "claude_code":
        # Simulate discovery of worker local MCPs
        passport = CapabilityProviderPassport(
            provider_id="claude_local_mcp_fs",
            provider_type="worker_local_mcp",
            owner_worker="claude_code",
            source="discovered",
            canonical_capabilities=["filesystem_read", "filesystem_write", "glob_search"],
            transparency="semi_transparent",
            invocation_mode="brokered_mcp",
            permissions=PassportPermissions(
                filesystem_read="scoped",
                filesystem_write="scoped",
                shell="limited",
                network="no",
                cloud_upload="no"
            ),
            risk_level="medium",
            cost_model=CostModel(known=True, attribution="provider_level", estimated_usd=0.0),
            verification=VerificationModel(probe_available=True, audition_required=True),
            trust_level="provisional" if safe else "untrusted",
            disabled_by_default=False
        )
        discovered.append(passport)
        
    elif worker_id == "openclaw":
        passport = CapabilityProviderPassport(
            provider_id="openclaw_local_mcp_network",
            provider_type="worker_local_mcp",
            owner_worker="openclaw",
            source="discovered",
            canonical_capabilities=["http_request", "network_ping"],
            transparency="opaque",
            invocation_mode="brokered_mcp",
            permissions=PassportPermissions(
                filesystem_read="none",
                filesystem_write="none",
                shell="none",
                network="yes",
                cloud_upload="yes"
            ),
            risk_level="high",
            cost_model=CostModel(known=False, attribution="unknown"),
            verification=VerificationModel(probe_available=False, audition_required=True),
            trust_level="untrusted",
            disabled_by_default=True
        )
        discovered.append(passport)
        
    return discovered
