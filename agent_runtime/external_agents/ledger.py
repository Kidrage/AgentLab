from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Optional
from datetime import datetime


class ExternalAgentLedger:
    """Tracks external agent interactions and verification status.

    Key P1-B rules:
    - add_handoff writes an entry with status=proposed.
    - update_result_status sets the handoff status to "submitted" and records
      evidence_status separately.  It does NOT auto-promote the
      artifact_gate_status — a human or supervisor must approve the gate.
    """

    def __init__(self, task_id: str, output_dir: Optional[str] = None):
        self.task_id = task_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"
        self.ledger_path = Path(self.output_dir) / "external_agent_ledger.yml"
        self.ledger_data = self._load_ledger()

    def _load_ledger(self) -> dict[str, Any]:
        """Load existing ledger or create new one."""
        if self.ledger_path.exists():
            with open(self.ledger_path, "r") as f:
                loaded = yaml.safe_load(f)
                if loaded and isinstance(loaded, dict):
                    return loaded
        ledger = {
            "task_id": self.task_id,
            "handoffs": [],
            "created_at": datetime.now().isoformat(),
        }
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "w") as f:
            yaml.safe_dump(ledger, f, sort_keys=False)
        return ledger

    def add_handoff(self, handoff_data: dict[str, Any]) -> None:
        """Add a new handoff to the ledger."""
        handoff_entry = {
            "handoff_id": handoff_data["handoff_id"],
            "agent_id": handoff_data["target"]["agent_id"],
            "status": handoff_data["target"]["status"],  # "proposed"
            "billing_mode": handoff_data["budget"]["billing_mode"],
            "token_visibility": handoff_data["budget"]["external_token_visibility"],
            "api_cost_visible": handoff_data["budget"]["api_cost_visible"],
            "evidence_status": "missing",
            "artifact_gate_status": "pending",  # never auto-passed
            "created_at": datetime.now().isoformat(),
            "skill_usage_events": [],
        }
        self.ledger_data["handoffs"].append(handoff_entry)
        self._save_ledger()

    def update_result_status(self, result_data: dict[str, Any]) -> None:
        """Update ledger when a result is submitted.

        Sets status → "submitted" (NOT "completed"/"accepted").
        Records evidence_status separately from artifact_gate_status.
        """
        handoff_id = result_data.get("handoff_id", "")
        evidence_status = result_data.get("evidence_status", "missing")

        for handoff in self.ledger_data["handoffs"]:
            if handoff["handoff_id"] == handoff_id:
                # Status becomes "submitted" — gate must be approved separately
                handoff["status"] = "submitted"
                handoff["evidence_status"] = evidence_status
                # artifact_gate_status stays "pending" until explicit approval
                handoff["updated_at"] = datetime.now().isoformat()
                break
        self._save_ledger()

    def add_skill_usage(
        self, handoff_id: str, skill_data: dict[str, Any]
    ) -> None:
        """Add skill usage event to the ledger."""
        for handoff in self.ledger_data["handoffs"]:
            if handoff["handoff_id"] == handoff_id:
                skill_event = {
                    "event": (
                        "planned"
                        if "suggested_external_skills" in skill_data
                        else "used"
                    ),
                    "executor": skill_data.get("executor", "unknown"),
                    "cost_mode": skill_data.get("cost_mode", "unknown"),
                    "timestamp": datetime.now().isoformat(),
                }
                if "success" in skill_data:
                    skill_event["success"] = skill_data["success"]
                if "quality_score" in skill_data:
                    skill_event["quality_score"] = skill_data["quality_score"]
                handoff["skill_usage_events"].append(skill_event)
                self._save_ledger()
                break

    def _save_ledger(self) -> None:
        """Save ledger data to disk."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "w") as f:
            yaml.safe_dump(self.ledger_data, f, sort_keys=False)

    def get_ledger(self) -> dict[str, Any]:
        """Return current ledger data."""
        return self.ledger_data