"""Allowlisted deterministic Attempt for detached narrative projection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.task_runtime_v2.runtime import InvalidTransition, TaskRuntime


TOOL_ID = "agentlab.narrative.detached_state_projector"
TOOL_VERSION = "1"


class NarrativeProjectionAttemptExecutor:
    """Own the real TaskRuntime Attempt for deterministic state projection."""

    def __init__(self, agentlab_root: Path, *, project: str) -> None:
        self.agentlab_root = Path(agentlab_root).resolve()
        self.project = project
        self.runtime = TaskRuntime(self.agentlab_root, project=project)

    @staticmethod
    def _key(base: str, suffix: str) -> str:
        return f"{base}.{suffix}"

    def start(
        self,
        *,
        task_id: str,
        work_item_id: str,
        attempt_id: str,
        candidate_sha256: str,
        acceptance_record_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        projection = self.runtime.load_task(task_id)
        work_item = (projection.get("work_items") or {}).get(work_item_id)
        if (
            not isinstance(work_item, Mapping)
            or work_item.get("kind") != "verification"
            or work_item.get("requires_user_acceptance") is not True
        ):
            raise InvalidTransition("detached projection requires its governed verifier")
        classification = projection["task"].get("input_classification") or {}
        deterministic_tool = {
            "tool_id": TOOL_ID,
            "tool_version": TOOL_VERSION,
            "candidate_sha256": candidate_sha256,
            "acceptance_record_id": acceptance_record_id,
        }
        execution_contract = {
            "role": "Scribe",
            "executor_type": "deterministic_tool",
            "input_tier": classification.get("tier"),
            "route": classification.get("route"),
            "deterministic_tool": deterministic_tool,
        }
        attempt = (projection.get("attempts") or {}).get(attempt_id)
        if attempt is None:
            projection = self.runtime.schedule_attempt(
                task_id,
                work_item_id=work_item_id,
                attempt_id=attempt_id,
                worker=TOOL_ID,
                provider="agentlab-deterministic",
                execution_contract=execution_contract,
                idempotency_key=self._key(idempotency_key, "schedule"),
            )
            attempt = projection["attempts"][attempt_id]
        elif (
            attempt.get("work_item_id") != work_item_id
            or attempt.get("worker") != TOOL_ID
            or attempt.get("provider") != "agentlab-deterministic"
            or attempt.get("execution_contract") != execution_contract
        ):
            raise InvalidTransition("detached projection Attempt binding changed")
        if attempt.get("status") == "scheduled":
            projection = self.runtime.transition_attempt(
                task_id,
                attempt_id=attempt_id,
                status="running",
                idempotency_key=self._key(idempotency_key, "running"),
            )
        elif attempt.get("status") not in {"running", "succeeded"}:
            raise InvalidTransition("detached projection Attempt cannot continue")
        return {
            "projection": projection,
            "attempt_id": attempt_id,
            "deterministic_tool": deterministic_tool,
        }

    def complete(
        self,
        *,
        task_id: str,
        work_item_id: str,
        attempt_id: str,
        output_path: Path,
        deterministic_tool: Mapping[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        projection = self.runtime.load_task(task_id)
        attempt = (projection.get("attempts") or {}).get(attempt_id)
        if not isinstance(attempt, Mapping):
            raise InvalidTransition("detached projection Attempt is missing")
        if attempt.get("status") == "succeeded":
            return self.runtime.verify_attempt_execution_receipt(task_id, attempt_id)
        if attempt.get("status") != "running":
            raise InvalidTransition("detached projection Attempt is not running")
        task_root = self.runtime._task_dir(task_id).resolve(strict=True)
        output = Path(output_path).resolve(strict=True)
        if not output.is_file() or not output.is_relative_to(task_root):
            raise InvalidTransition("detached projection output is outside its Task")
        attempt_root = task_root / "attempt_logs" / attempt_id
        attempt_root.mkdir(parents=True, exist_ok=True)
        attempt_output = attempt_root / output.name
        atomic_write_text(attempt_output, output.read_text(encoding="utf-8"))
        receipt_path = attempt_root / "deterministic_execution_receipt.yml"
        receipt = {
            "schema_version": "task-runtime-deterministic-attempt-receipt/v1",
            "project": self.project,
            "task_id": task_id,
            "work_item_id": work_item_id,
            "attempt_id": attempt_id,
            "role": "Scribe",
            "worker": TOOL_ID,
            "provider": "agentlab-deterministic",
            "status": "pass",
            "output_path": attempt_output.relative_to(task_root).as_posix(),
            "output_sha256": hashlib.sha256(attempt_output.read_bytes()).hexdigest(),
            "deterministic_tool": dict(deterministic_tool),
            "model_execution": None,
        }
        atomic_write_yaml(receipt_path, receipt, sort_keys=False)
        outcome = {
            "execution_origin": "deterministic_tool_executor",
            "receipt_path": receipt_path.relative_to(task_root).as_posix(),
            "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "output_sha256": receipt["output_sha256"],
        }
        projection = self.runtime._transition_deterministic_attempt(
            task_id,
            attempt_id=attempt_id,
            idempotency_key=self._key(idempotency_key, "succeeded"),
            outcome=outcome,
        )
        verified = self.runtime.verify_attempt_execution_receipt(task_id, attempt_id)
        return {"projection": projection, **verified}
