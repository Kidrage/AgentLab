"""Skill discovery for local workers."""

from typing import List
from agent_runtime.capability_broker.provider_passport import (
    CapabilityProviderPassport, PassportPermissions, CostModel, VerificationModel
)

def discover_worker_skills(worker_id: str, safe: bool = True) -> List[CapabilityProviderPassport]:
    """Discover local skills exposed by a specific worker."""
    discovered = []
    
    if worker_id == "claude_code":
        # Simulate discovery of worker local skills
        passport = CapabilityProviderPassport(
            provider_id="claude_local_skill_code_review",
            provider_type="worker_local_skill",
            owner_worker="claude_code",
            source="discovered",
            canonical_capabilities=["code_review", "diff_risk_analysis"],
            transparency="opaque",
            invocation_mode="delegated_worker",
            permissions=PassportPermissions(
                filesystem_read="unknown",
                filesystem_write="possible",
                shell="possible",
                network="unknown",
                cloud_upload="unknown"
            ),
            risk_level="high",
            cost_model=CostModel(known=False, attribution="worker_level_only"),
            verification=VerificationModel(probe_available=False, audition_required=True),
            trust_level="provisional" if safe else "untrusted",
            disabled_by_default=True
        )
        discovered.append(passport)
        
    elif worker_id == "hermes":
        passport = CapabilityProviderPassport(
            provider_id="hermes_local_skill_planning",
            provider_type="worker_local_skill",
            owner_worker="hermes",
            source="discovered",
            canonical_capabilities=["multi_agent_planning", "step_supervision"],
            transparency="semi_transparent",
            invocation_mode="delegated_worker",
            permissions=PassportPermissions(
                filesystem_read="scoped",
                filesystem_write="scoped",
                shell="none",
                network="no",
                cloud_upload="no"
            ),
            risk_level="medium",
            cost_model=CostModel(known=True, attribution="provider_level", estimated_usd=0.01),
            verification=VerificationModel(probe_available=True, audition_required=False),
            trust_level="provisional" if safe else "untrusted",
            disabled_by_default=False
        )
        discovered.append(passport)
        
    return discovered
