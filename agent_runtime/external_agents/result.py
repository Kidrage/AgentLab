from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Optional
from datetime import datetime

from agent_runtime.external_agents.registry import registry as agent_registry


class ExternalResult:
    """Handles submission and validation of external agent results.

    Key P1-B design rules:
    - submit_result writes external_result.yml only; it does NOT auto-pass
      artifact gates.
    - evidence_status (complete/partial/missing) is separate from
      artifact_gate_status (pending/failed) — a human or supervisor must
      separately approve the gate.
    - cost fields default to null/unknown unless the submitter provides them.
    """

    def __init__(
        self, task_id: str, handoff_id: str, output_dir: Optional[str] = None
    ):
        self.task_id = task_id
        self.handoff_id = handoff_id
        self.output_dir = output_dir or f"projects/AgentLab/runs/{task_id}"
        self.result_id = f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def submit_result(self, result_data: dict[str, Any]) -> dict[str, Any]:
        """Submit and validate an external agent result.

        Returns a new dict with validated and defaulted fields; does NOT
        mutate the caller's dict.
        """
        self._validate_result_data(result_data)

        validated: dict[str, Any] = {
            "result_id": self.result_id,
            "handoff_id": result_data["handoff_id"],
            "task_id": result_data["task_id"],
            "executor": dict(result_data["executor"]),
            "summary": result_data.get("summary", ""),
            "status": result_data.get("status", "completed"),
            "submitted_at": datetime.now().isoformat(),
            "changed_files": list(result_data.get("changed_files") or []),
            "commands_run": list(result_data.get("commands_run") or []),
            "artifacts": list(result_data.get("artifacts") or []),
        }

        # --- evidence_status is a factual check, NOT a gate pass ---
        validated["evidence_status"] = self._evaluate_evidence(validated)

        # --- cost fields default to unknown/null ---
        validated.setdefault("cost_notes", "")
        validated.setdefault("api_cost_usd", None)
        validated.setdefault("subscription_quota_used", "unknown")
        validated.setdefault("pricing_status", "external_unknown")

        # --- ran claims without evidence → fail submission ---
        self._enforce_claims_evidence(validated)

        self._save_result_artifact(validated)
        return validated

    # ------------------------------------------------------------------
    def _validate_result_data(self, result_data: dict[str, Any]) -> None:
        required_fields = ["handoff_id", "task_id", "executor", "summary"]
        for field in required_fields:
            if field not in result_data:
                raise ValueError(f"Missing required field '{field}' in result data")

        executor = result_data["executor"]
        executor_fields = [
            "agent_id",
            "reported_by",
            "billing_mode",
            "token_visibility",
        ]
        for field in executor_fields:
            if field not in executor:
                raise ValueError(f"Missing required executor field '{field}'")

        if executor["token_visibility"] != "unknown":
            raise ValueError("token_visibility must be 'unknown'")

        agent = agent_registry.get_agent(executor["agent_id"])
        if agent and executor["billing_mode"] != agent["billing"]["mode"]:
            raise ValueError("Billing mode mismatch with agent configuration")

    # ------------------------------------------------------------------
    def _evaluate_evidence(self, result_data: dict[str, Any]) -> str:
        status = result_data.get("status", "completed")
        if status in ("failed", "rejected"):
            return "missing"

        has_commands = bool(result_data.get("commands_run"))
        has_artifacts = bool(result_data.get("artifacts"))
        has_changed = bool(result_data.get("changed_files"))

        if has_commands or has_artifacts:
            return "complete"
        if has_changed:
            return "partial"
        return "missing"

    # ------------------------------------------------------------------
    def _enforce_claims_evidence(self, result_data: dict[str, Any]) -> None:
        changed_files = result_data.get("changed_files") or []
        commands_run = result_data.get("commands_run") or []
        artifacts = result_data.get("artifacts") or []

        # Changed files without any evidence → reject
        if changed_files and not (artifacts or commands_run):
            raise ValueError(
                "Changed files require evidence of commands run or artifacts"
            )

        summary = (result_data.get("summary") or "").lower()
        claims_keywords = ["ran tests", "ran build", "executed commands"]
        if any(kw in summary for kw in claims_keywords):
            if not (commands_run or artifacts):
                raise ValueError(
                    "Build/test claims require evidence of commands run or artifacts"
                )

    # ------------------------------------------------------------------
    def _save_result_artifact(self, result_data: dict[str, Any]) -> None:
        output_path = Path(self.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        with open(output_path / "external_result.yml", "w") as f:
            yaml.safe_dump(result_data, f, sort_keys=False)