from dataclasses import dataclass
from typing import Dict, Any, List
from datetime import datetime
import hashlib

@dataclass
class DecisionCard:
    decision_id: str
    decision_type: str
    status: str
    risk_level: str
    reason: str
    requested_by: str
    task_id: str
    project: str
    phase_id: str
    capabilities: List[str]
    estimated_cost_usd: float
    evidence_artifacts: List[str]
    created_at: str
    updated_at: str
    expires_at: str

    @classmethod
    def create(cls, **kwargs) -> 'DecisionCard':
        # Deterministic ID generation
        raw = f"{kwargs.get('task_id')}_{kwargs.get('reason')}_{kwargs.get('created_at')}"
        d_id = kwargs.get("decision_id") or hashlib.md5(raw.encode()).hexdigest()[:12]
        return cls(
            decision_id=d_id,
            decision_type=kwargs.get("decision_type", "manual"),
            status=kwargs.get("status", "pending"),
            risk_level=kwargs.get("risk_level", "low"),
            reason=kwargs.get("reason", ""),
            requested_by=kwargs.get("requested_by", "system"),
            task_id=kwargs.get("task_id", ""),
            project=kwargs.get("project", ""),
            phase_id=kwargs.get("phase_id", ""),
            capabilities=kwargs.get("capabilities", []),
            estimated_cost_usd=kwargs.get("estimated_cost_usd", 0.0),
            evidence_artifacts=kwargs.get("evidence_artifacts", []),
            created_at=kwargs.get("created_at", datetime.utcnow().isoformat()),
            updated_at=kwargs.get("updated_at", datetime.utcnow().isoformat()),
            expires_at=kwargs.get("expires_at", "")
        )

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}
