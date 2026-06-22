"""Capability schema model and loader for AgentLab."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    capability_id: str
    display_name: str
    description: str
    risk_level: str  # "low" | "medium" | "high"


class CapabilitySchema:
    def __init__(self, capabilities: dict[str, CapabilityDefinition]) -> None:
        self._capabilities = capabilities

    @classmethod
    def load_from_file(cls, config_path: Path) -> "CapabilitySchema":
        if not config_path.exists():
            return cls({})
        try:
            content = config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content) or {}
            capabilities_data = data.get("capabilities", {})
            
            capabilities = {}
            for cap_id, cap_info in capabilities_data.items():
                capabilities[cap_id] = CapabilityDefinition(
                    capability_id=cap_id,
                    display_name=cap_info.get("display_name", cap_id),
                    description=cap_info.get("description", ""),
                    risk_level=cap_info.get("risk_level", "medium"),
                )
            return cls(capabilities)
        except Exception as e:
            # Fallback or empty registry on error
            return cls({})

    def get_capability(self, capability_id: str) -> Optional[CapabilityDefinition]:
        return self._capabilities.get(capability_id)

    def list_capabilities(self) -> list[CapabilityDefinition]:
        return sorted(self._capabilities.values(), key=lambda c: c.capability_id)

    def get_all(self) -> dict[str, CapabilityDefinition]:
        return self._capabilities
