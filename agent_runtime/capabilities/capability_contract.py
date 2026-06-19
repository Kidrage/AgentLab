"""S9 capability contract models.

These models describe what AgentLab may do. They do not execute external tools.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    MISSING_BACKEND = "missing_backend"
    DISABLED = "disabled"
    REQUIRES_APPROVAL = "requires_approval"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    capability_id: str
    display_name: str
    description: str
    modality: str
    backend_type: str
    status: CapabilityStatus
    permissions: tuple[str, ...]
    risk_level: RiskLevel
    evidence_required: tuple[str, ...]
    missing_backend_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "display_name": self.display_name,
            "description": self.description,
            "modality": self.modality,
            "backend_type": self.backend_type,
            "status": self.status.value,
            "permissions": list(self.permissions),
            "risk_level": self.risk_level.value,
            "evidence_required": list(self.evidence_required),
            "missing_backend_reason": self.missing_backend_reason,
        }
