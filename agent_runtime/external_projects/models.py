"""M1 external project registry models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AdapterContract:
    expected_inputs: tuple[str, ...]
    expected_outputs: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdapterContract":
        return cls(
            expected_inputs=tuple(data.get("expected_inputs", ())),
            expected_outputs=tuple(data.get("expected_outputs", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_inputs": list(self.expected_inputs),
            "expected_outputs": list(self.expected_outputs),
        }


@dataclass(frozen=True, slots=True)
class RiskProfile:
    level: str
    reasons: tuple[str, ...]
    requires_approval: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RiskProfile":
        return cls(
            level=str(data.get("level", "medium")),
            reasons=tuple(data.get("reasons", ())),
            requires_approval=bool(data.get("requires_approval", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "reasons": list(self.reasons),
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True, slots=True)
class ExternalProject:
    project_id: str
    display_name: str
    source_url: str
    role: str
    default_enabled: bool
    integration_stage: str
    capabilities: tuple[str, ...]
    risk: RiskProfile
    permissions: dict[str, Any]
    adapter_contract: AdapterContract
    notes: tuple[str, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExternalProject":
        return cls(
            project_id=str(data["project_id"]),
            display_name=str(data["display_name"]),
            source_url=str(data["source_url"]),
            role=str(data.get("role", "reference")),
            default_enabled=bool(data.get("default_enabled", False)),
            integration_stage=str(data.get("integration_stage", "registry_only")),
            capabilities=tuple(data.get("capabilities", ())),
            risk=RiskProfile.from_dict(data.get("risk", {})),
            permissions=dict(data.get("permissions", {})),
            adapter_contract=AdapterContract.from_dict(data.get("adapter_contract", {})),
            notes=tuple(data.get("notes", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "display_name": self.display_name,
            "source_url": self.source_url,
            "role": self.role,
            "default_enabled": self.default_enabled,
            "integration_stage": self.integration_stage,
            "capabilities": list(self.capabilities),
            "risk": self.risk.to_dict(),
            "permissions": self.permissions,
            "adapter_contract": self.adapter_contract.to_dict(),
            "notes": list(self.notes),
        }
