"""Lightweight dataclass schemas for Context Governance artifacts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ContextProfile:
    task_id: str
    modality: list[str] = field(default_factory=list)
    source_type: list[str] = field(default_factory=list)
    length_tier: str = "S"
    precision_risk: str = "low"
    freshness_required: bool = False
    structure_level: str = "unstructured"
    action_type: list[str] = field(default_factory=list)
    compression_safety: str = "safe_lossy"
    recommended_strategy: list[str] = field(default_factory=list)
    information_type: str = "short_prompt"
    compression_level: str = "C0_direct"
    budget_policy: str = "small_task"
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextBudget:
    task_id: str
    max_input_tokens: int = 12000
    max_output_tokens: int = 4000
    max_tool_output_tokens: int = 1200
    max_sources: int = 8
    max_files: int = 12
    max_crops: int = 4
    estimated_baseline_tokens: int = 0
    estimated_packed_tokens: int = 0
    estimated_savings_ratio: float = 0.0
    budget_policy: str = "small_task"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["estimated_savings_ratio"] = round(max(0.0, min(1.0, self.estimated_savings_ratio)), 4)
        return data


@dataclass
class PackedSection:
    section_id: str
    title: str
    content: str
    tokens_estimate: int = 0
    source_refs: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OmittedSection:
    reason: str
    source_ref: str
    can_drill_down: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExternalizedArtifact:
    path: str
    kind: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRef:
    path: str
    kind: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContextPack:
    task_id: str
    profile: dict[str, Any]
    budget: dict[str, Any]
    strategy: list[str] = field(default_factory=list)
    packed_sections: list[dict[str, Any]] = field(default_factory=list)
    omitted_sections: list[dict[str, Any]] = field(default_factory=list)
    externalized_artifacts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)