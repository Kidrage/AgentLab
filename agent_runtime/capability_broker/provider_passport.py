"""Passport data models for capability providers in the capability broker."""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

@dataclass
class PassportPermissions:
    filesystem_read: str = "unknown" # "scoped" | "full" | "limited" | "none" | "unknown"
    filesystem_write: str = "unknown" # "possible" | "scoped" | "none" | "unknown"
    shell: str = "unknown" # "limited" | "possible" | "none" | "unknown"
    network: str = "unknown" # "yes" | "no" | "unknown"
    cloud_upload: str = "unknown"

    @classmethod
    def from_dict(cls, d: dict) -> "PassportPermissions":
        return cls(**d)

@dataclass
class CostModel:
    known: bool = False
    attribution: str = "unknown" # "provider_level" | "worker_level_only" | "unknown"
    estimated_usd: float = 0.0
    estimated_tokens: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "CostModel":
        return cls(**d)

@dataclass
class VerificationModel:
    probe_available: bool = False
    audition_required: bool = True
    last_successful_use: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "VerificationModel":
        return cls(**d)

@dataclass
class CapabilityProviderPassport:
    provider_id: str
    provider_type: str # "agentlab_owned_tool" | "agentlab_owned_skill" | "agentlab_brokered_mcp" | "direct_api_provider" | "worker_local_skill" | "worker_local_mcp" | "external_handoff_provider"
    source: str = "discovered" # "discovered" | "declared" | "agentlab_owned" | "external"
    owner_worker: Optional[str] = None
    canonical_capabilities: List[str] = field(default_factory=list)
    transparency: str = "transparent" # "transparent" | "semi_transparent" | "opaque"
    invocation_mode: str = "direct" # "direct" | "brokered_mcp" | "delegated_worker" | "manual_handoff"
    permissions: PassportPermissions = field(default_factory=PassportPermissions)
    risk_level: str = "medium" # "low" | "medium" | "high" | "critical"
    cost_model: CostModel = field(default_factory=CostModel)
    verification: VerificationModel = field(default_factory=VerificationModel)
    trust_level: str = "provisional" # "trusted" | "provisional" | "untrusted" | "disabled"
    disabled_by_default: bool = False
    allowed_projects: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CapabilityProviderPassport":
        data = d.copy()
        if "permissions" in data and isinstance(data["permissions"], dict):
            data["permissions"] = PassportPermissions.from_dict(data["permissions"])
        if "cost_model" in data and isinstance(data["cost_model"], dict):
            data["cost_model"] = CostModel.from_dict(data["cost_model"])
        if "verification" in data and isinstance(data["verification"], dict):
            data["verification"] = VerificationModel.from_dict(data["verification"])
        return cls(**data)
