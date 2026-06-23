"""Serializable, explainable route-decision contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class RejectedWorker:
    worker: str
    reason: str


@dataclass(slots=True)
class CostEstimate:
    known: bool = False
    policy: str = "unknown"
    tier: str = "unknown"


@dataclass(slots=True)
class RouteConstraints:
    allowed_files: list[str] = field(default_factory=list)
    forbidden_files: list[str] = field(default_factory=list)
    commands_allowed: list[str] = field(default_factory=list)
    commands_forbidden: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RouteDecision:
    project_id: str
    phase_id: str
    task_id: str
    role: str
    selected_worker: str | None
    selected_command: str | None
    selection_reason: list[str] = field(default_factory=list)
    rejected_workers: list[RejectedWorker] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=list)
    risk_level: str = "medium"
    approval_required: bool = False
    approval_reasons: list[str] = field(default_factory=list)
    activation_decision: str = "activate"
    mode: str = "hybrid_local_company"
    tier: str = "performance"
    cost_estimate: CostEstimate = field(default_factory=CostEstimate)
    fallback_workers: list[str] = field(default_factory=list)
    constraints: RouteConstraints = field(default_factory=RouteConstraints)
    evidence_paths: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        for name in ("project_id", "phase_id", "task_id", "role"):
            if not getattr(self, name):
                errors.append(f"missing {name}")
        if self.activation_decision == "activate" and not self.selected_worker:
            errors.append("active route requires selected_worker")
        if not self.required_capabilities:
            errors.append("required_capabilities must not be empty")
        return errors

    def to_dict(self, *, wrapped: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["rejected_workers"] = [asdict(item) for item in self.rejected_workers]
        return {"route_decision": payload} if wrapped else payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RouteDecision":
        raw = dict(data.get("route_decision", data))
        raw["rejected_workers"] = [
            item if isinstance(item, RejectedWorker) else RejectedWorker(**item)
            for item in raw.get("rejected_workers", [])
        ]
        if not isinstance(raw.get("cost_estimate"), CostEstimate):
            raw["cost_estimate"] = CostEstimate(**(raw.get("cost_estimate") or {}))
        if not isinstance(raw.get("constraints"), RouteConstraints):
            raw["constraints"] = RouteConstraints(**(raw.get("constraints") or {}))
        return cls(**raw)

    def write(self, path: Path) -> Path:
        errors = self.validate()
        if errors:
            raise ValueError("invalid route decision: " + "; ".join(errors))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return path
