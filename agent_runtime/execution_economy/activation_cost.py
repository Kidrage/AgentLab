"""Activation cost data models for execution economy."""

from dataclasses import dataclass, field, asdict
from typing import Optional, Any, List

@dataclass
class FixedStartupCost:
    raw_prompt_tokens: int = 0
    cacheable_prompt_tokens: int = 0
    expected_cache_hit_rate: float = 0.0
    effective_prompt_tokens: int = 0
    estimated_cached_input_discount: str = "none" # "none" | "low" | "medium" | "high" | "unknown"
    estimated_latency_s: float = 0.0
    operator_friction: str = "low" # "low" | "medium" | "high"

    @classmethod
    def from_dict(cls, d: dict) -> "FixedStartupCost":
        return cls(**d)

@dataclass
class CacheProfile:
    stable_prefix_hash: Optional[str] = None
    skill_context_hash: Optional[str] = None
    mcp_manifest_hash: Optional[str] = None
    last_cache_hit_observed: str = "unknown" # "true" | "false" | "unknown"
    cache_confidence: str = "unknown" # "low" | "medium" | "high" | "unknown"

    @classmethod
    def from_dict(cls, d: dict) -> "CacheProfile":
        # Keep string conversion for last_cache_hit_observed if it is bool
        val = d.get("last_cache_hit_observed")
        if val is True or val == "true":
            d["last_cache_hit_observed"] = "true"
        elif val is False or val == "false":
            d["last_cache_hit_observed"] = "false"
        else:
            d["last_cache_hit_observed"] = "unknown"
        return cls(**d)

@dataclass
class VariableCost:
    task_specific_context_tokens: int = 0
    context_tokens_per_kb: int = 0
    output_tokens_expected: int = 0
    dollars_per_call: str = "unknown" # string or float/unknown

    @classmethod
    def from_dict(cls, d: dict) -> "VariableCost":
        return cls(**d)

@dataclass
class NonTokenCosts:
    coordination_cost: str = "low" # "low" | "medium" | "high"
    permission_risk: str = "low" # "low" | "medium" | "high" | "critical"
    state_mutation_risk: str = "low" # "low" | "medium" | "high" | "critical"

    @classmethod
    def from_dict(cls, d: dict) -> "NonTokenCosts":
        return cls(**d)

@dataclass
class ActivationCost:
    worker_id: str
    fixed_startup_cost: FixedStartupCost = field(default_factory=FixedStartupCost)
    cache_profile: CacheProfile = field(default_factory=CacheProfile)
    variable_cost: VariableCost = field(default_factory=VariableCost)
    non_token_costs: NonTokenCosts = field(default_factory=NonTokenCosts)
    hidden_costs: List[str] = field(default_factory=list)
    confidence: str = "medium" # "low" | "medium" | "high"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActivationCost":
        data = d.copy()
        if "fixed_startup_cost" in data and isinstance(data["fixed_startup_cost"], dict):
            data["fixed_startup_cost"] = FixedStartupCost.from_dict(data["fixed_startup_cost"])
        if "cache_profile" in data and isinstance(data["cache_profile"], dict):
            data["cache_profile"] = CacheProfile.from_dict(data["cache_profile"])
        if "variable_cost" in data and isinstance(data["variable_cost"], dict):
            data["variable_cost"] = VariableCost.from_dict(data["variable_cost"])
        if "non_token_costs" in data and isinstance(data["non_token_costs"], dict):
            data["non_token_costs"] = NonTokenCosts.from_dict(data["non_token_costs"])
        return cls(**data)
