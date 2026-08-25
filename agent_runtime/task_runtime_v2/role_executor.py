"""Execute one governed CLI role as a Task Runtime v2 Attempt."""

from __future__ import annotations

import hashlib
import fnmatch
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.narrative.outbound_transfer import (
    build_narrative_outbound_transfer_contract,
    evaluate_narrative_auto_approval,
)
from agent_runtime.outbound_context import is_forbidden_source_path
from agent_runtime.role_keys import canonical_role_name, normalize_role_key
from agent_runtime.schemas import AgentRoute, WorkflowPlan

from .input_tiers import TaskInputClassifier
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
        self._source_policy = TaskInputClassifier(self.root).sealed_source_policy()
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
        external_context_request: Mapping[str, Any] | None = None,
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
        projection = self.runtime.load_task(task_id)
        work_item = projection["work_items"].get(work_item_id)
        if work_item is None:
            raise EntityNotFound(f"work item {work_item_id!r} does not exist")
        role_name = canonical_role_name(role)
        resolved_sources: list[Path] = []
        total_source_bytes = 0
        read_scope = self._bound_read_scope(work_item, role=role_name)
        protocol_bound = isinstance(projection["task"].get("compiled_protocol"), dict)
        if source_paths and read_scope is None and not protocol_bound:
            raise ValueError("source_paths require an assigned active Project Agent")
        for source_path in source_paths or []:
            candidate = Path(source_path)
            if is_forbidden_source_path(candidate):
                raise ValueError("source_paths may not contain sensitive paths")
            if candidate.is_symlink():
                raise ValueError("source_paths may not contain symlinks")
            resolved = candidate.resolve(strict=True)
            protocol_source = protocol_bound and self._source_allowed_by_protocol(
                resolved,
                projection=projection,
                work_item=work_item,
                task_id=task_id,
            )
            source_kind = self._source_kind(resolved, task_id=task_id)
            if source_kind is None and protocol_source:
                source_kind = "PROTOCOL_DECLARED_SOURCE"
            if source_kind is None:
                raise ValueError(
                    "source_paths is outside governed project source roots"
                )
            if read_scope is not None and not self._source_allowed_by_manifest(
                resolved, task_id=task_id, read_scope=read_scope
            ):
                raise ValueError(
                    "source_paths is outside the assigned Agent read scope"
                )
            if read_scope is None and not protocol_source:
                raise ValueError("source_paths is outside the compiled protocol inputs")
            content = resolved.read_text(encoding="utf-8")
            total_source_bytes += len(content.encode("utf-8"))
            if total_source_bytes > int(self._source_policy["max_total_bytes"]):
                raise ValueError("sealed source_paths exceed the governed intake limit")
            resolved_sources.append(resolved)
            sealed_messages.append(
                {
                    "role": "user",
                    "content": (
                        f"{source_kind} "
                        f"{resolved.relative_to(self.root).as_posix()}\n{content}"
                    ),
                }
            )
        attempt = projection["attempts"].get(attempt_id)
        attempt_root = self.runtime.tasks_root / task_id / "attempt_logs" / attempt_id
        output_path = attempt_root / "output.md"
        receipt_path = attempt_root / "attempt_receipt.yml"
        if attempt is not None:
            existing_role = str(
                (attempt.get("execution_contract") or {}).get("role") or ""
            )
            if (
                attempt.get("work_item_id") != work_item_id
                or existing_role != role_name
            ):
                raise InvalidTransition(
                    f"Attempt {attempt_id!r} belongs to another execution identity"
                )
            if attempt.get("status") != "succeeded" or not receipt_path.is_file():
                raise InvalidTransition(f"Attempt {attempt_id!r} already exists")
            self.runtime.verify_attempt_execution_receipt(task_id, attempt_id)
            return {
                "projection": projection,
                "output_path": str(output_path),
                "receipt_path": str(receipt_path),
            }
        if external_context_request is None:
            raise ValueError(
                "new role execution requires an external context approval request"
            )
        classification = projection["task"].get("input_classification") or {}
        profile, provider, agent_model_profile = self._resolve_bound_profile(
            role_name,
            work_item,
        )
        recipient = (
            f"cli_agent:{str(profile.get('cli_agent') or '').strip()};"
            f"runtime_provider:{provider}"
        )
        external_context_contract = build_narrative_outbound_transfer_contract(
            self.root,
            project=self.project,
            task_id=task_id,
            recipient=recipient,
            purpose=str(external_context_request.get("purpose") or ""),
            minimal_fragment=str(
                external_context_request.get("minimal_fragment") or ""
            ),
            source_paths=resolved_sources,
            expires_at=str(external_context_request.get("expires_at") or ""),
            role=str(external_context_request.get("role") or role_name),
            defer_exact_payload_to_execution=True,
            source_inventory_required=bool(resolved_sources),
        )
        if external_context_contract is not None and (
            external_context_contract.get("recipient") != recipient
        ):
            raise ValueError(
                "external context recipient does not match resolved CLI agent"
            )
        execution_contract = {
            "role": role_name,
            "executor_type": "cli_agent",
            "input_tier": classification.get("tier"),
            "route": classification.get("route"),
            "invocation_contract": profile.get("invocation_contract"),
            "model_key": profile.get("default"),
            "model_id": profile.get("_resolved_model_id"),
            "runtime_provider": provider,
            "agent_model_profile": agent_model_profile,
            "model_tier": profile.get("_resolved_tier"),
        }
        if not classification.get("admission_ready"):
            if role_name != "Supervisor":
                raise InvalidTransition(
                    "only Supervisor may execute before input classification"
                )
            execution_contract["purpose"] = "input_classification"

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
            budget_mode=str(profile["_resolved_budget_mode"]),
            required_outputs=[
                str(contract["artifact_type"])
                for contract in (
                    (projection["task"].get("compiled_protocol") or {}).get(
                        "artifact_contracts"
                    )
                    or ()
                )
                if contract.get("producer_node") == work_item_id
            ],
            role_contract=dict(work_item.get("role_contract") or {}),
        )
        if external_context_contract is not None:
            request_scope = external_context_contract.get("request_scope")
            scope_sha256 = (
                str(request_scope.get("sha256") or "")
                if isinstance(request_scope, Mapping)
                else ""
            )
            if (
                external_context_contract.get("schema_version")
                != "narrative-outbound-transfer/v1"
                or external_context_contract.get("status")
                not in {"pending_approval", "pass"}
                or not str(external_context_contract.get("recipient") or "").strip()
                or not str(external_context_contract.get("purpose") or "").strip()
                or len(scope_sha256) != 64
            ):
                raise ValueError("external context contract is invalid")
            plan.execution_policy = {
                **dict(plan.execution_policy or {}),
                "external_context_approval_required": True,
                "external_context_payload_sha256_required": True,
                "external_context_scope_sha256_required": True,
                "external_context_scope_contract_valid": True,
                "external_context_scope_sha256": scope_sha256,
                "external_context_approval_signature_path": str(
                    external_context_request.get("approval_signature_path") or ""
                ),
                "external_context_transfer": {
                    "recipient": external_context_contract["recipient"],
                    "purpose": external_context_contract["purpose"],
                    "expires_at": external_context_contract["expires_at"],
                    "request_scope_sha256": scope_sha256,
                },
            }
            auto_approval = evaluate_narrative_auto_approval(
                self.root,
                project=self.project,
                task_id=task_id,
                recipient=recipient,
                role=str(external_context_request.get("role") or role_name),
                purpose=str(external_context_request.get("purpose") or ""),
                source_paths=resolved_sources,
                expires_at=str(external_context_request.get("expires_at") or ""),
            )
            if auto_approval["status"] == "pass":
                plan.execution_policy["external_context_auto_approval"] = auto_approval
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

        try:
            model_execution = self._validate_model_execution_result(
                result=result,
                role=role_name,
                profile=profile,
                provider=provider,
                attempt_root=attempt_root,
                task_root=self.runtime.tasks_root / task_id,
            )
            atomic_write_text(output_path, content)
            output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
            receipt = {
                "schema_version": "task-runtime-role-attempt-receipt/v1",
                "project": self.project,
                "task_id": task_id,
                "work_item_id": work_item_id,
                "attempt_id": attempt_id,
                "role": role_name,
                "worker": profile["cli_agent"],
                "provider": provider,
                "executor_provider": str(getattr(result, "provider", "") or ""),
                "model": str(getattr(result, "model", "") or ""),
                "model_execution": model_execution,
                "invocation_contract": profile.get("invocation_contract"),
                "input_tier": classification.get("tier"),
                "route": classification.get("route"),
                "status": "pass",
                "output_path": str(
                    output_path.relative_to(self.runtime.tasks_root / task_id)
                ),
                "output_sha256": output_sha256,
                "sealed_sources": [
                    {
                        "path": path.relative_to(self.root).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in resolved_sources
                ],
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
            projection = self.runtime._transition_executed_attempt(
                task_id,
                attempt_id=attempt_id,
                status="succeeded",
                outcome={
                    "execution_origin": "role_attempt_executor",
                    "receipt_path": str(
                        receipt_path.relative_to(self.runtime.tasks_root / task_id)
                    ),
                    "receipt_sha256": receipt_sha256,
                    "output_sha256": output_sha256,
                },
                idempotency_key=self._key(idempotency_key, "succeeded"),
            )
        except (InvalidTransition, OSError, ValueError) as exc:
            current = self.runtime.load_task(task_id)["attempts"].get(attempt_id) or {}
            if current.get("status") == "running":
                self.runtime.transition_attempt(
                    task_id,
                    attempt_id=attempt_id,
                    status="failed",
                    outcome={"error_type": type(exc).__name__, "error": str(exc)},
                    idempotency_key=self._key(idempotency_key, "failed"),
                )
            raise
        return {
            "projection": projection,
            "output_path": str(output_path),
            "receipt_path": str(receipt_path),
        }

    def _bound_read_scope(
        self,
        work_item: dict[str, Any],
        *,
        role: str,
    ) -> tuple[str, ...] | None:
        agent_id = work_item.get("assigned_agent_id")
        if agent_id is None:
            return None
        self.runtime._validate_project_agent_binding(
            assigned_agent_id=agent_id,
            agent_manifest_revision=work_item.get("agent_manifest_revision"),
            canonical_snapshot_id=work_item.get("canonical_snapshot_id"),
            contract_hash=work_item.get("effective_contract_hash"),
            execution_role=role,
        )
        from agent_runtime.project_agents import ProjectAgentRegistry
        from agent_runtime.project_truth import ProjectTruthStore

        manifest = ProjectAgentRegistry(
            ProjectTruthStore(self.root / "projects" / self.project)
        ).get(str(agent_id))
        if manifest.status != "active":
            raise ValueError("assigned Project Agent is not active")
        return tuple(str(item) for item in manifest.read_scope)

    def _source_allowed_by_manifest(
        self,
        path: Path,
        *,
        task_id: str,
        read_scope: tuple[str, ...],
    ) -> bool:
        project_root = (self.root / "projects" / self.project).resolve()
        relative = path.relative_to(project_root).as_posix()
        return any(fnmatch.fnmatchcase(relative, pattern) for pattern in read_scope)

    def _source_allowed_by_protocol(
        self,
        path: Path,
        *,
        projection: dict[str, Any],
        work_item: dict[str, Any],
        task_id: str,
    ) -> bool:
        compiled = projection["task"].get("compiled_protocol") or {}
        node_id = str(work_item.get("work_item_id") or "")
        fact_names = (compiled.get("source_fact_bindings") or {}).get(node_id) or []
        facts = projection["task"].get("input_profile") or {}
        for fact_name in fact_names:
            raw_root = facts.get(fact_name)
            if not isinstance(raw_root, str) or not raw_root.strip():
                continue
            candidate = Path(raw_root)
            roots = (
                [candidate]
                if candidate.is_absolute()
                else [
                    self.root / candidate,
                    self.root / "projects" / self.project / candidate,
                ]
            )
            for source_root in roots:
                if source_root.is_symlink() or not source_root.exists():
                    continue
                resolved_root = source_root.resolve(strict=True)
                if not resolved_root.is_relative_to(self.root):
                    continue
                expected_hash = str(
                    facts.get(f"{fact_name}_sha256") or ""
                )
                if expected_hash and (
                    len(expected_hash) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in expected_hash
                    )
                    or not resolved_root.is_file()
                    or hashlib.sha256(resolved_root.read_bytes()).hexdigest()
                    != expected_hash
                ):
                    continue
                project_root = (self.root / "projects" / self.project).resolve(
                    strict=True
                )
                if not resolved_root.is_relative_to(project_root):
                    observed_hash = (
                        hashlib.sha256(resolved_root.read_bytes()).hexdigest()
                        if resolved_root.is_file()
                        else ""
                    )
                    if (
                        resolved_root.is_relative_to(self.root)
                        and path == resolved_root
                        and len(expected_hash) == 64
                        and all(
                            character in "0123456789abcdef"
                            for character in expected_hash
                        )
                        and observed_hash == expected_hash
                    ):
                        return True
                    continue
                relative_root = resolved_root.relative_to(project_root)
                protocol_roots = set(
                    self._source_policy.get("project_roots") or []
                )
                task_inputs_root = self.runtime._task_dir(task_id) / "inputs"
                task_bound_runtime_source = (
                    bool(relative_root.parts)
                    and relative_root.parts[0] == "runtime"
                    and resolved_root.is_relative_to(task_inputs_root.resolve())
                )
                if (
                    not relative_root.parts
                    or (
                        relative_root.parts[0] not in protocol_roots
                        and not task_bound_runtime_source
                    )
                ):
                    continue
                if path == resolved_root or path.is_relative_to(resolved_root):
                    return True
        task_root = self.runtime._task_dir(task_id)
        gate_subject_types = {
            str(artifact_type)
            for gate in compiled.get("promotion_gate_bindings") or []
            if gate.get("work_item_id") == node_id
            for artifact_type in gate.get("subject_artifact_types") or []
        }
        gate_subject_paths = {
            (task_root / str(artifact.get("path") or "")).resolve(strict=False)
            for artifact in projection["artifacts"].values()
            if artifact.get("artifact_id") in gate_subject_types
        }
        if path in gate_subject_paths:
            return True
        dependencies = set(work_item.get("depends_on") or [])
        if not dependencies:
            return False
        dependency_attempt_ids = {
            attempt_id
            for attempt_id, attempt in projection["attempts"].items()
            if attempt.get("work_item_id") in dependencies
            and attempt.get("status") == "succeeded"
        }
        governed_paths = {
            (task_root / "attempt_logs" / attempt_id / "output.md").resolve(
                strict=False
            )
            for attempt_id in dependency_attempt_ids
        }
        governed_paths.update(
            (task_root / str(artifact.get("path") or "")).resolve(strict=False)
            for artifact in projection["artifacts"].values()
            if artifact.get("producer_attempt_id") in dependency_attempt_ids
        )
        return path in governed_paths

    def _resolve_bound_profile(
        self,
        role: str,
        work_item: dict[str, Any],
    ) -> tuple[dict[str, Any], str, str | None]:
        agent_id = work_item.get("assigned_agent_id")
        if agent_id is None:
            protocol_model_profile = str(
                work_item.get("agent_model_profile") or ""
            ).strip()
            profile, provider = self._resolve_profile(
                role,
                model_profile=protocol_model_profile or None,
            )
            return profile, provider, protocol_model_profile or None

        binding = {
            "assigned_agent_id": agent_id,
            "agent_manifest_revision": work_item.get("agent_manifest_revision"),
            "canonical_snapshot_id": work_item.get("canonical_snapshot_id"),
            "contract_hash": work_item.get("effective_contract_hash"),
        }
        self.runtime._validate_project_agent_binding(
            **binding,
            execution_role=role,
        )

        from agent_runtime.project_agents import ProjectAgentRegistry
        from agent_runtime.project_truth import ProjectTruthStore

        truth = ProjectTruthStore(self.root / "projects" / self.project)
        manifest = ProjectAgentRegistry(truth).get(str(agent_id))
        profile, provider = self._resolve_profile(
            role,
            model_profile=manifest.model_profile,
        )
        return profile, provider, manifest.model_profile

    def _resolve_profile(
        self,
        role: str,
        *,
        model_profile: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        from agent_runtime.cli_executor import _model_invocation_values

        profiles = yaml.safe_load(
            (self.root / "config" / "agent_model_profiles.yml").read_text(
                encoding="utf-8"
            )
        )
        tier_policy = profiles.get("tier_policy") or {}
        tier_definitions = tier_policy.get("tiers") or {}
        professional_profiles = profiles.get("professional_role_profiles") or {}
        requested = str(model_profile or "").strip().lower()
        tier = str(tier_policy.get("default_tier") or "performance")
        professional: Mapping[str, Any] | None = None
        if requested:
            selected_professional = professional_profiles.get(requested)
            if isinstance(selected_professional, dict):
                professional = selected_professional
                if professional.get("execution_kind") != "cli_agent":
                    raise InvalidTransition(
                        "Project Agent profile is not a CLI execution profile"
                    )
                if professional.get("base_role_key") != normalize_role_key(role):
                    raise InvalidTransition("Project Agent profile/base role mismatch")
                tier = str(professional.get("execution_tier") or "")
            else:
                matched = next(
                    (
                        name
                        for name, definition in tier_definitions.items()
                        if requested == str(name).lower()
                        or requested
                        in {
                            str(alias).lower()
                            for alias in (definition or {}).get(
                                "budget_aliases",
                                (),
                            )
                        }
                    ),
                    None,
                )
                if matched is None:
                    raise InvalidTransition(
                        f"unknown Agent model profile {model_profile!r}"
                    )
                tier = str(matched)
        profile = (
            profiles.get("modes", {})
            .get("full_cli", {})
            .get("tiers", {})
            .get(tier, {})
            .get(normalize_role_key(role))
        )
        if not isinstance(profile, dict) or profile.get("executor_type") != "cli_agent":
            raise InvalidTransition(f"no {tier} CLI profile for role {role!r}")
        profile = dict(profile)
        if professional is not None:
            strict_route = str(professional.get("capacity_route") or "").strip()
            if not strict_route:
                raise InvalidTransition(
                    "professional CLI profile requires an explicit capacity route"
                )
            capacity = (
                yaml.safe_load(
                    (self.root / "config" / "model_capacity.yml").read_text(
                        encoding="utf-8"
                    )
                )
                or {}
            )
            route = (capacity.get("routes") or {}).get(strict_route)
            expected = {
                "role": normalize_role_key(role),
                "worker": str(profile.get("cli_agent") or ""),
                "invocation_contract": str(profile.get("invocation_contract") or ""),
                "model_key": str(profile.get("default") or ""),
            }
            if not isinstance(route, Mapping) or any(
                str(route.get(field) or "") != value
                for field, value in expected.items()
            ):
                raise InvalidTransition(
                    "professional capacity route does not match its execution profile"
                )
            if (
                not str(route.get("pool") or "").strip()
                or route.get("approved_fallbacks") not in (None, [])
                or route.get("fallback_on") not in (None, [])
            ):
                raise InvalidTransition(
                    "professional capacity route must be explicit and fallback-free"
                )
            profile["capacity_route"] = strict_route
        model_values = _model_invocation_values(profile, self.root)
        provider = str(model_values.get("provider") or "")
        if not provider:
            raise InvalidTransition(f"model provider missing for role {role!r}")
        model_id = str(model_values.get("catalog_model_id") or "")
        if not model_id:
            raise InvalidTransition(f"model ID missing for role {role!r}")
        profile["_resolved_model_id"] = model_id
        profile["_resolved_tier"] = tier
        profile["_resolved_budget_mode"] = {
            "alter": "alter",
            "full": "max_quality",
            "performance": "balanced",
            "low": "frugal",
        }.get(tier, "balanced")
        return profile, provider

    def _build_plan(
        self,
        *,
        task_id: str,
        role: str,
        run_dir: Path,
        user_goal: str,
        budget_mode: str,
        required_outputs: list[str],
        role_contract: Mapping[str, Any],
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
            budget_mode=budget_mode,
            route=route,
            notes=[user_goal],
            included_agents={
                role: {
                    "required_outputs": list(required_outputs),
                    "protocol_role_contract": dict(role_contract),
                }
            },
        )

    def _source_kind(self, path: Path, *, task_id: str) -> str | None:
        if path.is_symlink() or not path.is_file():
            return None
        project_root = (self.root / "projects" / self.project).resolve(strict=False)
        if not path.is_relative_to(project_root):
            return None
        relative = path.relative_to(project_root)
        extensions = set(self._source_policy.get("allowed_extensions") or [])
        if path.suffix.lower() not in extensions:
            return None
        parts = relative.parts
        if not parts:
            return None
        if parts[0] in set(self._source_policy.get("project_roots") or []):
            return "AUTHORITATIVE_SOURCE"
        if (
            len(parts) >= 4
            and parts[0] == "runs"
            and parts[2] in set(self._source_policy.get("candidate_run_roots") or [])
        ):
            return "GOVERNED_CANDIDATE_SOURCE"
        runtime_prefix = ("runtime", "tasks", task_id)
        if len(parts) >= 5 and parts[:3] == runtime_prefix:
            if (
                len(parts) == 6
                and parts[3] == "attempt_logs"
                and parts[5] == self._source_policy.get("same_task_attempt_output")
            ):
                return "RUNTIME_V2_SOURCE"
            runtime_relative = "/".join(parts[3:-1])
            allowed_runtime_roots = set(
                self._source_policy.get("same_task_runtime_roots") or []
            )
            if any(
                runtime_relative == root or runtime_relative.startswith(f"{root}/")
                for root in allowed_runtime_roots
            ):
                return "RUNTIME_V2_SOURCE"
        return None

    def _validate_model_execution_result(
        self,
        *,
        result: Any,
        role: str,
        profile: dict[str, Any],
        provider: str,
        attempt_root: Path,
        task_root: Path,
    ) -> dict[str, Any]:
        usage = getattr(result, "raw_usage", {}) or {}
        expected_usage = {
            "cli_agent": profile["cli_agent"],
            "cli_model_key": profile["default"],
            "cli_catalog_model_id": profile["_resolved_model_id"],
            "cli_runtime_provider": provider,
            "exit_code": 0,
        }
        mismatch_flags = {
            "model_resolution_failed",
            "provider_model_mismatch",
            "qwen_provider_model_mismatch",
            "grok_provider_model_mismatch",
        }
        if (
            not isinstance(usage, dict)
            or any(usage.get(field) != value for field, value in expected_usage.items())
            or any(usage.get(flag) for flag in mismatch_flags)
        ):
            raise InvalidTransition(
                "CLI model execution metadata does not match the route"
            )
        receipt_value = str(usage.get("model_execution_receipt") or "")
        try:
            receipt_candidate = Path(receipt_value)
            receipt_path = receipt_candidate.resolve(strict=True)
            receipt_bytes = receipt_path.read_bytes()
            receipt = yaml.safe_load(receipt_bytes.decode("utf-8")) or {}
        except (OSError, RuntimeError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise InvalidTransition(
                "model execution receipt is missing or invalid"
            ) from exc
        if (
            receipt_candidate.is_symlink()
            or not receipt_path.is_relative_to(attempt_root.resolve(strict=False))
            or not isinstance(receipt, dict)
        ):
            raise InvalidTransition("model execution receipt escaped the Attempt")
        selected_provider = receipt.get("selected_provider", receipt.get("provider"))
        selected_model = (
            receipt.get("selected_model_id")
            or receipt.get("requested_model_id")
            or receipt.get("model")
        )
        profile_binding = receipt.get(
            "profile_binding_verified", receipt.get("profile_state_verified")
        )
        if (
            receipt.get("status") != "pass"
            or receipt.get("worker") != profile["cli_agent"]
            or receipt.get("invocation_contract") != profile["invocation_contract"]
            or receipt.get("role", role) != role
            or selected_provider != provider
            or selected_model != profile["_resolved_model_id"]
            or profile_binding is not True
            or receipt.get("command_binding_verified") is not True
            or receipt.get("fallback_detected") is True
            or receipt.get("provider_process_started") is not True
            or receipt.get("exit_code") != 0
            or receipt.get("issues") not in (None, [])
        ):
            raise InvalidTransition(
                "model execution receipt does not prove the selected route"
            )
        provider_binding = receipt.get("provider_model_binding_verified")
        if provider_binding is False:
            raise InvalidTransition("provider-reported model binding failed")
        return {
            "path": receipt_path.relative_to(task_root).as_posix(),
            "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "cli_agent": profile["cli_agent"],
            "model_key": profile["default"],
            "model_id": profile["_resolved_model_id"],
            "runtime_provider": provider,
            "executor_provider": str(getattr(result, "provider", "") or ""),
        }

    @staticmethod
    def _key(base: str, suffix: str) -> str:
        return f"{str(base)[:96]}-{suffix}"
