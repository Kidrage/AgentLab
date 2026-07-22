import yaml
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from agent_runtime.approvals.decision_card import DecisionCard
from agent_runtime.approvals.policy_engine import ApprovalDecision

class ApprovalLedger:
    def __init__(self, project: str):
        self.project = project
        self.approvals: List[DecisionCard] = []
        self.events: List[Dict[str, Any]] = []

    def create_decision_card(self, card: DecisionCard):
        self.approvals.append(card)
        self.events.append({
            "event_id": f"evt_{len(self.events)}",
            "decision_id": card.decision_id,
            "action": "created",
            "actor": "system",
            "reason": card.reason,
            "created_at": datetime.utcnow().isoformat()
        })

    def record_policy_decision(
        self,
        decision: ApprovalDecision,
        *,
        task_id: str = "",
        reason: str = "",
        decision_type: str = "policy",
    ) -> DecisionCard:
        """Persist automatic, human-required, and forbidden policy outcomes."""
        grant = decision.grant or {}
        status = {
            "auto_approved": "approved",
            "human_required": "pending",
            "forbidden": "rejected",
        }[decision.mode]
        actor = str(grant.get("actor") or "system")
        card = DecisionCard.create(
            decision_id=grant.get("grant_id"),
            decision_type=decision_type,
            status=status,
            risk_level="critical" if decision.mode == "forbidden" else "high" if decision.requires_human else "low",
            reason=reason or ";".join(decision.reasons),
            requested_by=actor,
            task_id=task_id,
            project=self.project,
            expires_at=grant.get("expires_at", ""),
            authorization={"decision_mode": decision.mode, **grant},
        )
        self.approvals.append(card)
        self.events.append({
            "event_id": f"evt_{len(self.events)}",
            "decision_id": card.decision_id,
            "action": decision.mode,
            "actor": actor,
            "reason": card.reason,
            "created_at": datetime.utcnow().isoformat(),
        })
        return card

    def list_pending(self) -> List[DecisionCard]:
        return [c for c in self.approvals if c.status == "pending"]

    def _update_decision(self, decision_id: str, status: str, actor: str, reason: str):
        for c in self.approvals:
            if c.decision_id == decision_id:
                if status == "approved" and c.authorization.get("decision_mode") == "forbidden":
                    return False
                c.status = status
                c.updated_at = datetime.utcnow().isoformat()
                self.events.append({
                    "event_id": f"evt_{len(self.events)}",
                    "decision_id": decision_id,
                    "action": status,
                    "actor": actor,
                    "reason": reason,
                    "created_at": datetime.utcnow().isoformat()
                })
                return True
        return False

    def approve_decision(self, decision_id: str, actor: str, reason: str) -> bool:
        return self._update_decision(decision_id, "approved", actor, reason)

    def reject_decision(self, decision_id: str, actor: str, reason: str) -> bool:
        return self._update_decision(decision_id, "rejected", actor, reason)

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "approvals": [c.to_dict() for c in self.approvals],
            "events": self.events
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ApprovalLedger':
        ledger = cls(data.get("project", "default"))
        for a in data.get("approvals", []):
            ledger.approvals.append(DecisionCard(**a))
        ledger.events = data.get("events", [])
        return ledger

def load_approval_ledger(path: Path) -> ApprovalLedger:
    if not path.exists():
        return ApprovalLedger("default")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ApprovalLedger.from_dict(data)

def write_approval_ledger(ledger: ApprovalLedger, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(yaml.safe_dump(ledger.to_dict(), sort_keys=False), encoding="utf-8")
    temp_path.replace(path)
