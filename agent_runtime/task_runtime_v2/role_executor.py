"""Execute one governed CLI role as a Task Runtime v2 Attempt."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

import yaml

from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.role_keys import canonical_role_name, normalize_role_key
from agent_runtime.schemas import AgentRoute, WorkflowPlan

from .runtime import EntityNotFound, InvalidTransition, TaskRuntime


class RoleAttemptExecutor:
    """Bridge configured AgentLab role sessions into the v2 event authority."""

    def __init__(
        self,
        agentlab_root: Path,
        *,
        project: str,
        cli_runner: Callable[..., Any] | None = None,
    ) -> None:
        self.root = Path(agentlab_root).resolve(strict=False)
        self.project = project
        self.runtime = TaskRuntime(self.root, project=project)
        if cli_runner is None:
            from agent_runtime.cli_executor import run_cli_agent

            cli_runner = run_cli_agent
        self._cli_runner = cli_runner

    def execute(
        self,
        *,
        task_id: str,
        work_item_id: str,
        attempt_id: str,
        role: str,
        messages: list[dict[str, str]],
        source_paths: list[Path] | None = None,
        idempotency_key: str,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Dispatch the recorded route and return its immutable Attempt receipt."""

        if not messages or any(
            not isinstance(item, dict)
            or not str(item.get("role") or "").strip()
            or not str(item.get("content") or "").strip()
            for item in messages
        ):
            raise ValueError("messages must contain role/content mappings")
        sealed_messages = [dict(item) for item in messages]
        resolved_sources: list[Path] = []
        total_source_bytes = 0
        for source_path in source_paths or []:
            resolved = Path(source_path).resolve(strict=True)
            if not resolved.is_relative_to(self.root) or resolved.is_symlink():
                raise ValueError("source_paths must be regular files inside AgentLab")
            content = resolved.read_text(encoding="utf-8")
            total_source_bytes += len(content.encode("utf-8"))
            if total_source_bytes > 2 * 1024 * 1024:
                raise ValueError("sealed source_paths exceed the 2 MiB intake limit")
            resolved_sources.append(resolved)
            sealed_messages.append(
                {
                    "role": "user",
                    "content": (
                        "AUTHORITATIVE_SOURCE "
                        f"{resolved.relative_to(self.root).as_posix()}\n{content}"
                    ),
                }
            )
        projection = self.runtime.load_task(task_id)
        work_item = projection["work_items"].get(work_item_id)
        if work_item is None:
            raise EntityNotFound(f"work item {work_item_id!r} does not exist")
        classification = projection["task"].get("input_classification") or {}
        role_name = canonical_role_name(role)
        profile, provider = self._resolve_profile(role_name)
        execution_contract = {
            "role": role_name,
            "input_tier": classification.get("tier"),
            "route": classification.get("route"),
            "invocation_contract": profile.get("invocation_contract"),
            "model_key": profile.get("default"),
        }
        if not classification.get("admission_ready"):
            if role_name != "Supervisor":
                raise InvalidTransition(
                    "only Supervisor may execute before input classification"
                )
            execution_contract["purpose"] = "input_classification"

        attempt = projection["attempts"].get(attempt_id)
        attempt_root = self.runtime.tasks_root / task_id / "attempt_logs" / attempt_id
        output_path = attempt_root / "output.md"
        receipt_path = attempt_root / "attempt_receipt.yml"
        if attempt is not None:
            if attempt.get("status") != "succeeded" or not receipt_path.is_file():
                raise InvalidTransition(f"Attempt {attempt_id!r} already exists")
            return {
                "projection": projection,
                "output_path": str(output_path),
                "receipt_path": str(receipt_path),
            }

        self.runtime.schedule_attempt(
            task_id,
            work_item_id=work_item_id,
            attempt_id=attempt_id,
            worker=str(profile["cli_agent"]),
            provider=provider,
            execution_contract=execution_contract,
            idempotency_key=idempotency_key,
        )
        self.runtime.transition_attempt(
            task_id,
            attempt_id=attempt_id,
            status="running",
            idempotency_key=self._key(idempotency_key, "running"),
        )
        attempt_root.mkdir(parents=True, exist_ok=True)
        plan = self._build_plan(
            task_id=task_id,
            role=role_name,
            run_dir=attempt_root,
            user_goal=str(projection["task"]["user_goal"]),
        )
        try:
            result = self._cli_runner(
                plan,
                role_name,
                profile,
                timeout=timeout,
                sealed_messages=sealed_messages,
                outbound_source_paths=resolved_sources,
            )
        except Exception as exc:
            self.runtime.transition_attempt(
                task_id,
                attempt_id=attempt_id,
                status="failed",
                outcome={"error_type": type(exc).__name__, "error": str(exc)},
                idempotency_key=self._key(idempotency_key, "failed"),
            )
            raise

        status = str(getattr(result, "status", "blocked_user_decision"))
        content = str(getattr(result, "content", "") or "")
        if status != "completed" or not content.strip():
            projection = self.runtime.transition_attempt(
                task_id,
                attempt_id=attempt_id,
                status="failed",
                outcome={
                    "provider_status": status,
                    "error": str(getattr(result, "error", "") or ""),
                },
                idempotency_key=self._key(idempotency_key, "failed"),
            )
            return {
                "projection": projection,
                "output_path": None,
                "receipt_path": None,
            }

        output_path.write_text(content, encoding="utf-8")
        output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        receipt = {
            "schema_version": "task-runtime-role-attempt-receipt/v1",
            "project": self.project,
            "task_id": task_id,
            "work_item_id": work_item_id,
            "attempt_id": attempt_id,
            "role": role_name,
            "worker": profile["cli_agent"],
            "provider": str(getattr(result, "provider", provider) or provider),
            "model": str(getattr(result, "model", "") or ""),
            "invocation_contract": profile.get("invocation_contract"),
            "input_tier": classification.get("tier"),
            "route": classification.get("route"),
            "status": "pass",
            "output_path": str(output_path.relative_to(self.runtime.tasks_root / task_id)),
            "output_sha256": output_sha256,
            "usage": {
                "input_tokens": getattr(result, "input_tokens", None),
                "output_tokens": getattr(result, "output_tokens", None),
                "total_tokens": getattr(result, "total_tokens", None),
            },
            "model_execution_receipt": (getattr(result, "raw_usage", {}) or {}).get(
                "model_execution_receipt"
            ),
        }
        atomic_write_yaml(receipt_path, receipt)
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        projection = self.runtime.transition_attempt(
            task_id,
            attempt_id=attempt_id,
            status="succeeded",
            outcome={
                "receipt_path": str(
                    receipt_path.relative_to(self.runtime.tasks_root / task_id)
                ),
                "receipt_sha256": receipt_sha256,
                "output_sha256": output_sha256,
            },
            idempotency_key=self._key(idempotency_key, "succeeded"),
        )
        return {
            "projection": projection,
            "output_path": str(output_path),
            "receipt_path": str(receipt_path),
        }

    def _resolve_profile(self, role: str) -> tuple[dict[str, Any], str]:
        profiles = yaml.safe_load(
            (self.root / "config" / "agent_model_profiles.yml").read_text(
                encoding="utf-8"
            )
        )
        profile = (
            profiles.get("modes", {})
            .get("full_cli", {})
            .get("tiers", {})
            .get("performance", {})
            .get(normalize_role_key(role))
        )
        if not isinstance(profile, dict) or profile.get("executor_type") != "cli_agent":
            raise InvalidTransition(f"no performance CLI profile for role {role!r}")
        profile = dict(profile)
        catalog = yaml.safe_load(
            (self.root / "config" / "model_catalog.yml").read_text(encoding="utf-8")
        )
        model = (catalog.get("models") or {}).get(profile.get("default")) or {}
        provider = str(model.get("runtime_provider") or model.get("provider") or "")
        if not provider:
            raise InvalidTransition(f"model provider missing for role {role!r}")
        return profile, provider

    def _build_plan(
        self, *, task_id: str, role: str, run_dir: Path, user_goal: str
    ) -> WorkflowPlan:
        project_root = self.root / "projects" / self.project
        route = AgentRoute(task_size="small", agents=[role])
        return WorkflowPlan(
            project=self.project,
            task_id=task_id,
            agentlab_root=str(self.root),
            project_root=str(project_root),
            repo_path=str(project_root),
            run_dir=str(run_dir),
            user_request_path=str(run_dir / "sealed_user_request.md"),
            budget_mode="balanced",
            route=route,
            notes=[user_goal],
        )

    @staticmethod
    def _key(base: str, suffix: str) -> str:
        return f"{str(base)[:96]}-{suffix}"
