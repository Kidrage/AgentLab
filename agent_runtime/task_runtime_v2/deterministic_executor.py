"""Allowlisted, non-model execution path for Task Runtime v2 Attempts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
import hashlib

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.narrative.metric_universe import (
    TOOL_ID,
    TOOL_VERSION,
    metric_universe_input_contract,
    project_metric_universe,
)
from .runtime import InvalidTransition, TaskRuntime


class DeterministicToolExecutor:
    """Execute only code-owned tools whose identity is pinned in the contract."""

    def __init__(self, agentlab_root: Path, *, project: str) -> None:
        self.agentlab_root = Path(agentlab_root).resolve(strict=True)
        self.project = project
        self.runtime = TaskRuntime(self.agentlab_root, project=project)

    @staticmethod
    def _key(value: str, phase: str) -> str:
        digest = hashlib.sha256(f"{value}:{phase}".encode("utf-8")).hexdigest()
        return f"deterministic-{phase}-{digest[:32]}"

    def execute_metric_universe(
        self,
        *,
        task_id: str,
        work_item_id: str,
        attempt_id: str,
        metric_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Schedule and execute one exact metric-universe projection."""

        projection = self.runtime.load_task(task_id)
        work_item = (projection.get("work_items") or {}).get(work_item_id)
        if (
            not isinstance(work_item, Mapping)
            or work_item.get("kind") != "metric-universe"
            or work_item.get("assigned_agent_id") != "state_projector"
        ):
            raise InvalidTransition(
                "metric universe requires the registered state_projector work item"
            )
        input_contract = metric_universe_input_contract(
            self.agentlab_root,
            project=self.project,
            metric_id=metric_id,
        )
        classification = projection["task"].get("input_classification") or {}
        deterministic_tool = {
            key: input_contract[key]
            for key in (
                "tool_id",
                "tool_version",
                "metric_id",
                "subject_root",
                "input_tree_sha256",
                "input_count",
            )
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
            raise InvalidTransition(
                "existing Attempt does not match deterministic tool contract"
            )
        if attempt.get("status") == "succeeded":
            verification = self.runtime.verify_attempt_execution_receipt(
                task_id,
                attempt_id,
            )
            return {
                "schema_version": "deterministic-tool-execution-result/v1",
                "status": "pass",
                "idempotent_replay": True,
                **verification,
            }
        if attempt.get("status") == "scheduled":
            projection = self.runtime.transition_attempt(
                task_id,
                attempt_id=attempt_id,
                status="running",
                idempotency_key=self._key(idempotency_key, "running"),
            )
            attempt = projection["attempts"][attempt_id]
        if attempt.get("status") != "running":
            raise InvalidTransition(
                "deterministic Attempt must be scheduled or running"
            )

        task_root = self.runtime._task_dir(task_id).resolve(strict=True)
        attempt_root = task_root / "attempt_logs" / attempt_id
        attempt_root.mkdir(parents=True, exist_ok=True)
        if attempt_root.is_symlink():
            raise InvalidTransition(
                "deterministic Attempt log root may not be a symlink"
            )
        output_path = attempt_root / f"metric_universe_{metric_id}.yml"
        result = project_metric_universe(
            self.agentlab_root,
            project=self.project,
            task_id=task_id,
            attempt_id=attempt_id,
            metric_id=metric_id,
            work_item_id=work_item_id,
            output_path=output_path,
        )
        producer = result.get("producer")
        if (
            not isinstance(producer, Mapping)
            or producer.get("tool_id") != TOOL_ID
            or producer.get("tool_version") != TOOL_VERSION
            or producer.get("input_tree_sha256")
            != deterministic_tool["input_tree_sha256"]
        ):
            raise InvalidTransition(
                "deterministic output does not match scheduled input"
            )
        output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
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
            "output_path": output_path.relative_to(task_root).as_posix(),
            "output_sha256": output_sha256,
            "deterministic_tool": deterministic_tool,
            "model_execution": None,
        }
        atomic_write_yaml(receipt_path, receipt)
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        outcome = {
            "execution_origin": "deterministic_tool_executor",
            "receipt_path": receipt_path.relative_to(task_root).as_posix(),
            "receipt_sha256": receipt_sha256,
            "output_sha256": output_sha256,
        }
        projection = self.runtime._transition_deterministic_attempt(
            task_id,
            attempt_id=attempt_id,
            idempotency_key=self._key(idempotency_key, "succeeded"),
            outcome=outcome,
        )
        verified = self.runtime.verify_attempt_execution_receipt(
            task_id,
            attempt_id,
        )
        return {
            "schema_version": "deterministic-tool-execution-result/v1",
            "status": "pass",
            "idempotent_replay": False,
            "artifact": result["artifact"],
            "receipt_path": receipt_path.relative_to(
                self.agentlab_root
            ).as_posix(),
            "projection": projection,
            **verified,
        }


__all__ = ["DeterministicToolExecutor"]
