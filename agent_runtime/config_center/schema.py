"""Config value descriptors and layer schema for M2-5 Config Center."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ConfigLayer(Enum):
    """Ordered config layers (higher value = higher priority)."""

    GLOBAL_DEFAULTS = 1
    ENVIRONMENT_PROFILE = 2
    LOCAL_WORKER_REGISTRY = 3
    ROLE_ASSIGNMENT_POLICY = 4
    COST_POLICY = 5
    RISK_POLICY = 6
    PROJECT_OVERRIDE = 7
    EXECUTOR_OVERRIDE = 8
    SKILL_OVERRIDE = 9
    CAPABILITY_OVERRIDE = 10
    USER_APPROVAL_OVERRIDE = 11
    RUNTIME_TEMPORARY = 12


@dataclass
class ConfigValue:
    """A resolved config value with source-layer metadata."""

    key: str
    value: Any
    layer: ConfigLayer
    overridden_from: list[ConfigLayer] = field(default_factory=list)
    is_secret: bool = False

    @property
    def is_overridden(self) -> bool:
        return len(self.overridden_from) > 0

    @property
    def source_label(self) -> str:
        return self.layer.name.lower()


@dataclass
class ConfigKeySchema:
    """Schema definition for a single config key."""

    key: str
    type_: str = "str"  # str, int, float, bool, list, dict
    required: bool = False
    default: Any = None
    description: str = ""
    ui_group: str = "general"
    ui_label: str = ""
    secret: bool = False
    allowed_values: list[Any] | None = None

    def validate_value(self, value: Any) -> list[str]:
        """Return a list of error messages; empty = valid."""
        errors: list[str] = []
        if value is None:
            if self.required:
                errors.append(f"error: {self.key} is required but missing")
            return errors
        type_map = {
            "str": str,
            "int": int,
            "float": (int, float),
            "bool": bool,
            "list": list,
            "dict": dict,
        }
        expected = type_map.get(self.type_)
        if expected is not None and not isinstance(value, expected):
            errors.append(f"error: {self.key} expected {self.type_}, got {type(value).__name__}")
        if self.allowed_values is not None and value not in self.allowed_values:
            errors.append(f"error: {self.key} value {value!r} not in allowed {self.allowed_values}")
        return errors


@dataclass
class ConfigSchema:
    """Full schema for the Config Center — all known keys with layer priority."""

    keys: dict[str, ConfigKeySchema] = field(default_factory=dict)
    layer_order: list[ConfigLayer] = field(
        default_factory=lambda: [
            ConfigLayer.GLOBAL_DEFAULTS,
            ConfigLayer.ENVIRONMENT_PROFILE,
            ConfigLayer.LOCAL_WORKER_REGISTRY,
            ConfigLayer.ROLE_ASSIGNMENT_POLICY,
            ConfigLayer.COST_POLICY,
            ConfigLayer.RISK_POLICY,
            ConfigLayer.PROJECT_OVERRIDE,
            ConfigLayer.EXECUTOR_OVERRIDE,
            ConfigLayer.SKILL_OVERRIDE,
            ConfigLayer.CAPABILITY_OVERRIDE,
            ConfigLayer.USER_APPROVAL_OVERRIDE,
            ConfigLayer.RUNTIME_TEMPORARY,
        ]
    )

    def get(self, key: str) -> ConfigKeySchema | None:
        return self.keys.get(key)
