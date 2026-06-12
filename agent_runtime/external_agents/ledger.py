from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml


# ============================================================
# Dataclasses (internal)
# ============================================================
@dataclass
class _ExternalHandoffLedgerEntry:
    """Internal dataclass for a single ledger entry."""
    handoff_id: str
    agent_id: str
    status: str
    billing_mode: str
    token_visibility: str
    api_cost_visible: bool
    created_at: Optional[str] = None
    submitted_at: Optional[str] = None
    evidence_status: str = "missing"
    artifact_gate_status: str = "pending"
    skill_usage_events: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class _ExternalAgentLedgerData:
    """Internal dataclass for the full ledger."""
    task_id: str
    handoffs: list[_ExternalHandoffLedgerEntry] = field(default_factory=list)


# ============================================================
# Standalone functions
# ============================================================
def load_external_agent_ledger(
    path: Path, task_id: str
) -> _ExternalAgentLedgerData:
    """Load the external agent ledger from a YAML file, or create a new one."""
    if path.exists():
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        if raw and isinstance(raw, dict):
            entries_raw = raw.get("handoffs") or []
            entries: list[_ExternalHandoffLedgerEntry] = []
            for e in entries_raw:
                if isinstance(e, dict):
                    entries.append(
                        _ExternalHandoffLedgerEntry(
                            handoff_id=e.get("handoff_id", ""),
                            agent_id=e.get("agent_id", ""),
                            status=e.get("status", "proposed"),
                            billing_mode=e.get("billing_mode", "unknown"),
                            token_visibility=e.get(
                                "token_visibility", "unknown"
                            ),
                            api_cost_visible=e.get("api_cost_visible", False),
                            created_at=e.get("created_at"),
                            submitted_at=e.get("submitted_at"),
                            evidence_status=e.get("evidence_status", "missing"),
                            artifact_gate_status=e.get(
                                "artifact_gate_status", "pending"
                            ),
                            skill_usage_events=list(
                                e.get("skill_usage_events") or []
                            ),
                        )
                    )
            return _ExternalAgentLedgerData(
                task_id=task_id, handoffs=entries
            )
    return _ExternalAgentLedgerData(task_id=task_id)


def write_external_agent_ledger(
    ledger: _ExternalAgentLedgerData, path: Path
) -> None:
    """Serialize the ledger to a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "task_id": ledger.task_id,
        "handoffs": [asdict(h) for h in ledger.handoffs],
    }
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, default_flow_style=False)


def record_handoff_created(
    ledger_path: Path,
    task_id: str,
    handoff_id: str,
    agent_id: str,
    billing_mode: str,
    token_visibility: str = "unknown",
    api_cost_visible: bool = False,
    skill_usage_events: Optional[list[str]] = None,
) -> None:
    """Record a new handoff in the ledger with status='proposed'."""
    ledger = load_external_agent_ledger(ledger_path, task_id)
    entry = _ExternalHandoffLedgerEntry(
        handoff_id=handoff_id,
        agent_id=agent_id,
        status="proposed",
        billing_mode=billing_mode,
        token_visibility=token_visibility,
        api_cost_visible=api_cost_visible,
        created_at=datetime.now(timezone.utc).isoformat(),
        evidence_status="missing",
        artifact_gate_status="pending",
        skill_usage_events=list(skill_usage_events or []),
    )
    ledger.handoffs.append(entry)
    write_external_agent_ledger(ledger, ledger_path)


def record_result_submitted(
    ledger_path: Path,
    task_id: str,
    handoff_id: str,
    evidence_status: str,
) -> None:
    """Update ledger when a result is submitted.
    Sets status='submitted', NOT 'accepted'. Artifact gate stays pending.
    """
    ledger = load_external_agent_ledger(ledger_path, task_id)
    for entry in ledger.handoffs:
        if entry.handoff_id == handoff_id:
            entry.status = "submitted"
            entry.submitted_at = datetime.now(timezone.utc).isoformat()
            entry.evidence_status = evidence_status
            break
    write_external_agent_ledger(ledger, ledger_path)


# ============================================================
# ExternalAgentLedger — the public class used by CLI and tests
# ============================================================
class ExternalAgentLedger:
    """Tracks external agent interactions and verification status.

    Key P1-B rules:
    - add_handoff writes an entry with status=proposed.
    - update_result_status sets status to 'submitted', NOT 'accepted'.
    - artifact_gate_status stays pending until explicit approval.
    """

    def __init__(self, task_id: str, output_dir: Optional[str] = None):
        self.task_id = task_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"
        self.ledger_path = Path(self.output_dir) / "external_agent_ledger.yml"
        self.ledger_data = self._load_ledger()

    def _load_ledger(self) -> dict[str, Any]:
        """Load or create ledger, return dict for backward compat."""
        ledger = load_external_agent_ledger(self.ledger_path, self.task_id)
        if not self.ledger_path.exists():
            write_external_agent_ledger(ledger, self.ledger_path)
        return {
            "task_id": ledger.task_id,
            "handoffs": [asdict(h) for h in ledger.handoffs],
            "created_at": (
                ledger.handoffs[0].created_at
                if ledger.handoffs
                else datetime.now(timezone.utc).isoformat()
            ),
        }

    def add_handoff(self, handoff_data: dict[str, Any]) -> None:
        """Add a new handoff entry from handoff dict."""
        record_handoff_created(
            ledger_path=self.ledger_path,
            task_id=self.task_id,
            handoff_id=handoff_data["handoff_id"],
            agent_id=handoff_data["target"]["agent_id"],
            billing_mode=handoff_data["budget"]["billing_mode"],
            token_visibility=handoff_data["budget"][
                "external_token_visibility"
            ],
            api_cost_visible=handoff_data["budget"]["api_cost_visible"],
        )
        self.ledger_data = self._load_ledger()

    def update_result_status(self, result_data: dict[str, Any]) -> None:
        """Update ledger when a result is submitted."""
        handoff_id = result_data.get("handoff_id", "")
        evidence_status = result_data.get("evidence_status", "missing")
        record_result_submitted(
            ledger_path=self.ledger_path,
            task_id=self.task_id,
            handoff_id=handoff_id,
            evidence_status=evidence_status,
        )
        self.ledger_data = self._load_ledger()

    def add_skill_usage(
        self, handoff_id: str, skill_data: dict[str, Any]
    ) -> None:
        """Add skill usage event to the ledger."""
        ledger = load_external_agent_ledger(self.ledger_path, self.task_id)
        for entry in ledger.handoffs:
            if entry.handoff_id == handoff_id:
                event = (
                    "planned"
                    if "suggested_external_skills" in skill_data
                    else "used"
                )
                skill_event: dict[str, Any] = {
                    "event": event,
                    "executor": skill_data.get("executor", "unknown"),
                    "cost_mode": skill_data.get("cost_mode", "unknown"),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                if "success" in skill_data:
                    skill_event["success"] = skill_data["success"]
                if "quality_score" in skill_data:
                    skill_event["quality_score"] = skill_data["quality_score"]
                entry.skill_usage_events.append(skill_event)
                break
        write_external_agent_ledger(ledger, self.ledger_path)
        self.ledger_data = self._load_ledger()

    def _save_ledger(self) -> None:
        """Persist current ledger_data to file."""
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        entries: list[_ExternalHandoffLedgerEntry] = []
        for h in self.ledger_data.get("handoffs", []):
            entries.append(
                _ExternalHandoffLedgerEntry(
                    handoff_id=h.get("handoff_id", ""),
                    agent_id=h.get("agent_id", ""),
                    status=h.get("status", "proposed"),
                    billing_mode=h.get("billing_mode", "unknown"),
                    token_visibility=h.get("token_visibility", "unknown"),
                    api_cost_visible=h.get("api_cost_visible", False),
                    created_at=h.get("created_at"),
                    submitted_at=h.get("submitted_at"),
                    evidence_status=h.get("evidence_status", "missing"),
                    artifact_gate_status=h.get(
                        "artifact_gate_status", "pending"
                    ),
                    skill_usage_events=list(
                        h.get("skill_usage_events") or []
                    ),
                )
            )
        ledger = _ExternalAgentLedgerData(
            task_id=self.ledger_data.get("task_id", self.task_id),
            handoffs=entries,
        )
        write_external_agent_ledger(ledger, self.ledger_path)

    def get_ledger(self) -> dict[str, Any]:
        """Return current ledger data as dict."""
        return dict(self.ledger_data)