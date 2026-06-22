"""Activation decision models for execution economy."""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

@dataclass
class DecisionCost:
    raw_tokens: int = 0
    cacheable_tokens: int = 0
    effective_tokens: int = 0
    estimated_usd: float = 0.0
    effective_estimated_usd: str = "none" # "none" | "low" | "medium" | "high"
    latency_class: str = "low" # "low" | "medium" | "high"
    coordination_cost: str = "low"
    permission_risk: str = "low"
    state_mutation_risk: str = "low"

@dataclass
class CacheVerdict:
    expected: str = "unknown" # "hit" | "partial_hit" | "miss" | "unknown"
    confidence: str = "unknown" # "low" | "medium" | "high"
    evidence: List[str] = field(default_factory=list)

@dataclass
class ExpectedBenefit:
    quality_gain: str = "none" # "none" | "low" | "medium" | "high"
    risk_reduction: str = "none"
    speed_gain: str = "none"
    recovery_value: str = "none"

@dataclass
class DecisionContextBudget:
    max_raw_tokens: int = 16000
    max_effective_tokens: int = 8000
    required_assets: List[str] = field(default_factory=list)
    excluded_assets: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_raw_tokens": self.max_raw_tokens,
            "max_effective_tokens": self.max_effective_tokens,
            "required_assets": self.required_assets,
            "excluded_assets": self.excluded_assets
        }

@dataclass
class ActivationDecision:
    role: str
    candidate_worker: str
    decision: str = "skip" # "spawn" | "skip" | "satisfy_by_deterministic" | "satisfy_by_cache" | "coalesce" | "defer" | "require_approval"
    activation_temperature: str = "unknown" # "deterministic" | "cold" | "warm_cached" | "hot_session" | "unknown"
    project_id: Optional[str] = None
    phase_id: Optional[str] = None
    task_id: Optional[str] = None
    satisfied_by: List[str] = field(default_factory=list)
    selected_worker: Optional[str] = None
    selected_provider: Optional[str] = None
    activation_cost: DecisionCost = field(default_factory=DecisionCost)
    cache_verdict: CacheVerdict = field(default_factory=CacheVerdict)
    expected_benefit: ExpectedBenefit = field(default_factory=ExpectedBenefit)
    marginal_utility_verdict: str = "unknown" # "justified" | "not_justified" | "unknown_requires_approval"
    reason: List[str] = field(default_factory=list)
    fallback: List[str] = field(default_factory=list)
    context_budget: DecisionContextBudget = field(default_factory=DecisionContextBudget)
    evidence_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ActivationDecision":
        data = d.copy()
        if "activation_cost" in data and isinstance(data["activation_cost"], dict):
            data["activation_cost"] = DecisionCost(**data["activation_cost"])
        if "cache_verdict" in data and isinstance(data["cache_verdict"], dict):
            data["cache_verdict"] = CacheVerdict(**data["cache_verdict"])
        if "expected_benefit" in data and isinstance(data["expected_benefit"], dict):
            data["expected_benefit"] = ExpectedBenefit(**data["expected_benefit"])
        if "context_budget" in data and isinstance(data["context_budget"], dict):
            data["context_budget"] = DecisionContextBudget(**data["context_budget"])
        return cls(**data)
