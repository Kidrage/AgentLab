"""Compile versioned production-pack protocols from declared task facts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from agent_runtime.atomic_io import safe_read_yaml
from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.narrative.author_team import (
    load_author_team_contract,
    select_author_team,
)
from agent_runtime.role_keys import normalize_role_key
from agent_runtime.task_runtime_v2 import (
    EntityNotFound,
    InvalidTransition,
    LedgerIntegrityError,
    TaskRuntime,
)


@dataclass(frozen=True)
class RoleBinding:
    """One governed role slot in a compiled production graph."""

    node_id: str
    role: str
    profile: str | None
    agent_model_profile: str | None
    execution_kind: str | None
    depends_on: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "profile": self.profile,
            "agent_model_profile": self.agent_model_profile,
            "execution_kind": self.execution_kind,
            "work_item_kind": _ROLE_KINDS.get(self.role, "production"),
            "title": f"{self.profile or self.role}: {self.node_id}",
            "depends_on": list(self.depends_on),
        }


@dataclass(frozen=True)
class ArtifactContract:
    """One immutable candidate artifact expected from a protocol node."""

    artifact_type: str
    producer_node: str
    candidate_only: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "producer_node": self.producer_node,
            "candidate_only": self.candidate_only,
        }


@dataclass(frozen=True)
class PromotionGateBinding:
    """One promotion gate bound to the node that must supply its evidence."""

    gate_id: str
    work_item_id: str
    evidence_kind: str
    subject_artifact_types: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "work_item_id": self.work_item_id,
            "evidence_kind": self.evidence_kind,
            "subject_artifact_types": list(self.subject_artifact_types),
        }


@dataclass(frozen=True)
class CompiledTaskGraph:
    """Deterministic execution graph produced by one versioned protocol."""

    protocol_ref: str
    pack_id: str
    task_facts_sha256: str
    role_bindings: tuple[RoleBinding, ...]
    artifact_contracts: tuple[ArtifactContract, ...]
    promotion_gates: tuple[str, ...]
    promotion_gate_bindings: tuple[PromotionGateBinding, ...]
    source_fact_bindings: dict[str, tuple[str, ...]]
    result_artifact_type: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "compiled-task-graph/v3",
            "protocol_ref": self.protocol_ref,
            "pack_id": self.pack_id,
            "task_facts_sha256": self.task_facts_sha256,
            "role_bindings": [binding.as_dict() for binding in self.role_bindings],
            "artifact_contracts": [
                contract.as_dict() for contract in self.artifact_contracts
            ],
            "promotion_gates": list(self.promotion_gates),
            "promotion_gate_bindings": [
                binding.as_dict() for binding in self.promotion_gate_bindings
            ],
            "source_fact_bindings": {
                node_id: list(facts)
                for node_id, facts in self.source_fact_bindings.items()
            },
            "result_artifact_type": self.result_artifact_type,
        }


_ROLE_KINDS = {
    "Supervisor": "planning",
    "RepoScout": "context",
    "InterfaceMapper": "planning",
    "Researcher": "research",
    "Observer": "observation",
    "Coder": "implementation",
    "ArtifactProducer": "artifact-production",
    "NarrativePlanner": "planning",
    "Writer": "prose",
    "Reviewer": "quality-review",
    "TesterAuditor": "validation",
    "Verifier": "verification",
    "Scribe": "verification",
}
_PROTOCOL_SOURCE_ROOTS = {"production", "project_brain", "reset_manifests"}


class ProductionProtocolRunner:
    """Bind and materialize one protocol graph through the Task Runtime seam."""

    def __init__(
        self,
        agentlab_root: Path,
        *,
        project: str,
        role_executor_factory: Callable[[Path, str], Any] | None = None,
    ):
        self.agentlab_root = Path(agentlab_root).resolve()
        self.project = str(project)
        self.runtime = TaskRuntime(self.agentlab_root, project=self.project)
        self._role_executor_factory = role_executor_factory

    def prepare(self, task_id: str) -> dict[str, Any]:
        """Compile and atomically materialize missing protocol WorkItems."""

        projection = self.runtime.load_task(task_id)
        task = projection["task"]
        protocol_ref = str(task.get("protocol_ref") or "")
        task_facts = task.get("input_profile")
        if not protocol_ref or not isinstance(task_facts, Mapping):
            raise InvalidTransition("Task is not bound to protocol facts")
        graph = compile_production_protocol(
            self.agentlab_root,
            protocol_ref=protocol_ref,
            task_facts=task_facts,
        )
        graph_document = graph.as_dict()
        existing_graph = task.get("compiled_protocol")
        if existing_graph is None:
            projection = self.runtime.bind_compiled_protocol(
                task_id,
                compiled_graph=graph_document,
                idempotency_key=f"protocol-{graph.task_facts_sha256[:24]}",
            )
        elif existing_graph != graph_document:
            raise InvalidTransition(
                "Task protocol compilation no longer matches its ledger"
            )

        expected_ids = [binding.node_id for binding in graph.role_bindings]
        existing_items = projection["work_items"]
        unexpected = sorted(set(existing_items) - set(expected_ids))
        if unexpected:
            raise InvalidTransition(
                "Task contains nodes outside its compiled protocol graph: "
                + ", ".join(unexpected)
            )
        materialized = [
            node_id for node_id in expected_ids if node_id in existing_items
        ]
        if materialized and len(materialized) != len(expected_ids):
            raise InvalidTransition(
                "Task contains a partially materialized protocol graph"
            )
        if materialized:
            for binding in graph.role_bindings:
                item = existing_items[binding.node_id]
                expected = {
                    "job_id": "job-main",
                    "kind": _ROLE_KINDS.get(binding.role, "production"),
                    "title": f"{binding.profile or binding.role}: {binding.node_id}",
                    "depends_on": list(binding.depends_on),
                    "protocol_role": binding.role,
                    "protocol_profile": binding.profile,
                    "agent_model_profile": binding.agent_model_profile,
                    "execution_kind": binding.execution_kind,
                }
                if any(item.get(field) != value for field, value in expected.items()):
                    raise InvalidTransition(
                        f"materialized protocol node is stale: {binding.node_id}"
                    )
            return projection

        items = [
            {
                "job_id": "job-main",
                "work_item_id": binding.node_id,
                "kind": _ROLE_KINDS.get(binding.role, "production"),
                "title": f"{binding.profile or binding.role}: {binding.node_id}",
                "depends_on": list(binding.depends_on),
                "requires_user_acceptance": False,
                "protocol_role": binding.role,
                "protocol_profile": binding.profile,
                "agent_model_profile": binding.agent_model_profile,
                "execution_kind": binding.execution_kind,
            }
            for binding in graph.role_bindings
        ]
        return self.runtime.create_work_items(
            task_id,
            batch_id=f"protocol-{graph.task_facts_sha256[:24]}",
            items=items,
            idempotency_key=f"materialize-{graph.task_facts_sha256[:24]}",
            protocol_materialization_sha256=_document_sha256(graph_document),
        )

    def execute_node(
        self,
        task_id: str,
        *,
        work_item_id: str,
        messages: list[dict[str, Any]],
        source_paths: list[Path],
        external_context_request: dict[str, Any],
        idempotency_key: str,
        attempt_id: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute one compiled node through RoleAttemptExecutor and bind outputs."""

        projection = self.prepare(task_id)
        task = projection["task"]
        compiled = task["compiled_protocol"]
        binding = next(
            (
                item
                for item in compiled["role_bindings"]
                if item["node_id"] == work_item_id
            ),
            None,
        )
        if binding is None:
            raise InvalidTransition(
                f"WorkItem is not in the compiled protocol graph: {work_item_id}"
            )
        if task["status"] == "created":
            projection = self.runtime.transition_task(
                task_id,
                status="ready",
                idempotency_key=f"{idempotency_key}-task-ready",
            )
        if projection["task"]["status"] == "ready":
            projection = self.runtime.transition_task(
                task_id,
                status="running",
                idempotency_key=f"{idempotency_key}-task-running",
            )
        work_item = projection["work_items"][work_item_id]
        if work_item["status"] == "ready":
            projection = self.runtime.transition_work_item(
                task_id,
                work_item_id=work_item_id,
                status="running",
                idempotency_key=f"{idempotency_key}-work-running",
            )
            work_item = projection["work_items"][work_item_id]
        if work_item["status"] not in {"running", "waiting_review"}:
            raise InvalidTransition(
                f"compiled WorkItem is not executable: {work_item['status']}"
            )
        successful_attempts = [
            (existing_id, existing)
            for existing_id, existing in projection["attempts"].items()
            if existing.get("work_item_id") == work_item_id
            and existing.get("status") == "succeeded"
        ]
        succeeded = successful_attempts[-1] if successful_attempts else None
        if succeeded is None:
            from agent_runtime.task_runtime_v2.role_executor import (
                RoleAttemptExecutor,
            )

            resolved_attempt_id = attempt_id or f"attempt-{work_item_id}-001"
            governed_sources = self._governed_sources(
                task_id,
                projection=projection,
                binding=binding,
                source_paths=source_paths,
            )
            if self._is_deterministic_binding(binding):
                result = self._execute_deterministic_node(
                    task_id,
                    work_item_id=work_item_id,
                    attempt_id=resolved_attempt_id,
                    binding=binding,
                    source_paths=governed_sources,
                    idempotency_key=f"{idempotency_key}-attempt",
                )
            else:
                executor = (
                    self._role_executor_factory(self.agentlab_root, self.project)
                    if self._role_executor_factory is not None
                    else RoleAttemptExecutor(
                        self.agentlab_root,
                        project=self.project,
                    )
                )
                result = executor.execute(
                    task_id=task_id,
                    work_item_id=work_item_id,
                    attempt_id=resolved_attempt_id,
                    role=str(binding["role"]),
                    messages=messages,
                    source_paths=governed_sources,
                    external_context_request=external_context_request,
                    idempotency_key=f"{idempotency_key}-attempt",
                    timeout=timeout,
                )
            projection = result["projection"]
            attempt = projection["attempts"][resolved_attempt_id]
            if attempt["status"] != "succeeded" or result["output_path"] is None:
                return {
                    "status": "attempt_failed",
                    "work_item_id": work_item_id,
                    "attempt_id": resolved_attempt_id,
                    "projection": projection,
                }
            succeeded = (resolved_attempt_id, attempt)
            output_path = Path(result["output_path"]).resolve(strict=True)
        else:
            resolved_attempt_id, attempt = succeeded
            outcome = attempt.get("outcome") or {}
            output_path = (
                self.runtime._task_dir(task_id)
                / "attempt_logs"
                / resolved_attempt_id
                / "output.md"
            ).resolve(strict=True)
            if (
                outcome.get("output_sha256")
                != hashlib.sha256(output_path.read_bytes()).hexdigest()
            ):
                raise InvalidTransition(
                    "successful protocol Attempt output has drifted"
                )

        output_text = output_path.read_text(encoding="utf-8")
        for contract in compiled["artifact_contracts"]:
            if contract["producer_node"] != work_item_id:
                continue
            artifact_type = str(contract["artifact_type"])
            already_recorded = any(
                artifact.get("artifact_id") == artifact_type
                and artifact.get("producer_attempt_id") == resolved_attempt_id
                for artifact in projection["artifacts"].values()
            )
            if already_recorded:
                continue
            staging_path = (
                self.runtime._task_dir(task_id)
                / "artifacts"
                / "staging"
                / f"{work_item_id}-{artifact_type}.md"
            )
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(staging_path, output_text)
            digest = hashlib.sha256(staging_path.read_bytes()).hexdigest()
            version_id = f"pv-{work_item_id[:32]}-{artifact_type[:32]}-{digest[:16]}"
            projection = self.runtime.record_artifact_version(
                task_id,
                artifact_id=artifact_type,
                version_id=version_id,
                attempt_id=resolved_attempt_id,
                path=staging_path,
                media_type="text/markdown",
                idempotency_key=f"{idempotency_key}-artifact-{artifact_type}",
            )

        required_gates = {
            binding["gate_id"]
            for binding in compiled["promotion_gate_bindings"]
            if binding["work_item_id"] == work_item_id
        }
        missing_gates = sorted(required_gates - set(projection["protocol_gates"]))
        if missing_gates:
            if projection["work_items"][work_item_id]["status"] == "running":
                projection = self.runtime.transition_work_item(
                    task_id,
                    work_item_id=work_item_id,
                    status="waiting_review",
                    idempotency_key=f"{idempotency_key}-waiting-review",
                )
            return {
                "status": "waiting_review",
                "work_item_id": work_item_id,
                "attempt_id": resolved_attempt_id,
                "missing_gates": missing_gates,
                "projection": projection,
            }
        projection = self.runtime.transition_work_item(
            task_id,
            work_item_id=work_item_id,
            status="accepted",
            idempotency_key=f"{idempotency_key}-accepted",
        )
        return {
            "status": "accepted",
            "work_item_id": work_item_id,
            "attempt_id": resolved_attempt_id,
            "projection": projection,
        }

    def _governed_sources(
        self,
        task_id: str,
        *,
        projection: dict[str, Any],
        binding: Mapping[str, Any],
        source_paths: list[Path],
    ) -> list[Path]:
        """Bind a node to declared source facts and accepted predecessor outputs."""

        task_root = self.runtime._task_dir(task_id)
        governed = [Path(item) for item in source_paths]
        compiled = projection["task"]["compiled_protocol"]
        fact_names = (compiled.get("source_fact_bindings") or {}).get(
            str(binding["node_id"])
        ) or []
        facts = projection["task"].get("input_profile") or {}
        for fact_name in fact_names:
            raw_source = Path(str(facts.get(fact_name) or ""))
            candidates = (
                [raw_source]
                if raw_source.is_absolute()
                else [
                    self.agentlab_root / raw_source,
                    self.agentlab_root / "projects" / self.project / raw_source,
                ]
            )
            source_root = next(
                (
                    candidate.resolve(strict=True)
                    for candidate in candidates
                    if candidate.exists()
                ),
                None,
            )
            if source_root is None or source_root.is_symlink():
                raise InvalidTransition(
                    f"compiled protocol source fact is unavailable: {fact_name}"
                )
            project_root = (self.agentlab_root / "projects" / self.project).resolve(
                strict=True
            )
            try:
                relative_source_root = source_root.relative_to(project_root)
            except ValueError as exc:
                raise InvalidTransition(
                    f"compiled protocol source fact is outside its Project: {fact_name}"
                ) from exc
            if (
                not relative_source_root.parts
                or relative_source_root.parts[0] not in _PROTOCOL_SOURCE_ROOTS
            ):
                raise InvalidTransition(
                    f"compiled protocol source fact is not canonical: {fact_name}"
                )
            if source_root.is_file():
                governed.append(source_root)
            elif not any(
                Path(path).resolve(strict=True).is_relative_to(source_root)
                for path in source_paths
            ):
                raise InvalidTransition(
                    f"compiled protocol source root requires selected files: {fact_name}"
                )
        for dependency in binding.get("depends_on") or []:
            item = projection["work_items"].get(dependency)
            if item is None or item.get("status") != "accepted":
                raise InvalidTransition(
                    f"protocol dependency is not accepted: {dependency}"
                )
            attempts = [
                (attempt_id, attempt)
                for attempt_id, attempt in projection["attempts"].items()
                if attempt.get("work_item_id") == dependency
                and attempt.get("status") == "succeeded"
            ]
            if not attempts:
                raise InvalidTransition(
                    f"protocol dependency has no successful Attempt: {dependency}"
                )
            attempt_id, _attempt = attempts[-1]
            governed.append(task_root / "attempt_logs" / attempt_id / "output.md")
            governed.extend(
                task_root / str(artifact["path"])
                for artifact in projection["artifacts"].values()
                if artifact.get("producer_attempt_id") == attempt_id
            )
        gate_subject_types = {
            str(artifact_type)
            for gate in compiled.get("promotion_gate_bindings") or []
            if gate.get("work_item_id") == binding.get("node_id")
            for artifact_type in gate.get("subject_artifact_types") or []
        }
        governed.extend(
            task_root / str(artifact["path"])
            for artifact in projection["artifacts"].values()
            if artifact.get("artifact_id") in gate_subject_types
        )
        deduplicated: list[Path] = []
        seen: set[Path] = set()
        for path in governed:
            resolved = path.resolve(strict=True)
            if resolved not in seen:
                deduplicated.append(resolved)
                seen.add(resolved)
        return deduplicated

    def _is_deterministic_binding(self, binding: Mapping[str, Any]) -> bool:
        return binding.get("execution_kind") == "deterministic_tool"

    def _execute_deterministic_node(
        self,
        task_id: str,
        *,
        work_item_id: str,
        attempt_id: str,
        binding: Mapping[str, Any],
        source_paths: list[Path],
        idempotency_key: str,
    ) -> dict[str, Any]:
        projection = self.runtime.load_task(task_id)
        classification = projection["task"]["input_classification"]
        tool = {
            "tool_id": f"agentlab.protocol.{binding.get('profile') or work_item_id}",
            "tool_version": "1",
            "protocol_ref": projection["task"]["protocol_ref"],
            "node_id": work_item_id,
        }
        contract = {
            "role": binding["role"],
            "executor_type": "deterministic_tool",
            "input_tier": classification["tier"],
            "route": classification["route"],
            "agent_model_profile": binding.get("agent_model_profile"),
            "deterministic_tool": tool,
        }
        self.runtime.schedule_attempt(
            task_id,
            work_item_id=work_item_id,
            attempt_id=attempt_id,
            worker="agentlab-protocol-projector",
            provider="agentlab-deterministic",
            execution_contract=contract,
            idempotency_key=idempotency_key,
        )
        self.runtime.transition_attempt(
            task_id,
            attempt_id=attempt_id,
            status="running",
            idempotency_key=f"{idempotency_key}-running",
        )
        task_root = self.runtime._task_dir(task_id)
        attempt_root = task_root / "attempt_logs" / attempt_id
        attempt_root.mkdir(parents=True, exist_ok=True)
        output_path = attempt_root / "output.md"
        source_hashes = {
            path.relative_to(self.agentlab_root).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in source_paths
        }
        artifact_inputs = {
            str(artifact["artifact_id"]): {
                "version_id": version_id,
                "sha256": artifact["sha256"],
            }
            for version_id, artifact in projection["artifacts"].items()
            if artifact.get("producer_attempt_id")
            in {
                attempt_id
                for attempt_id, attempt in projection["attempts"].items()
                if attempt.get("work_item_id") in set(binding.get("depends_on") or [])
            }
        }
        atomic_write_yaml(
            output_path,
            {
                "schema_version": "protocol-deterministic-projection/v1",
                "protocol_ref": projection["task"]["protocol_ref"],
                "task_id": task_id,
                "work_item_id": work_item_id,
                "profile": binding.get("profile"),
                "status": "candidate_only",
                "source_hashes": source_hashes,
                "artifact_inputs": artifact_inputs,
                "task_facts_sha256": projection["task"]["compiled_protocol"][
                    "task_facts_sha256"
                ],
            },
        )
        output_sha256 = hashlib.sha256(output_path.read_bytes()).hexdigest()
        receipt_path = attempt_root / "deterministic_execution_receipt.yml"
        atomic_write_yaml(
            receipt_path,
            {
                "schema_version": "task-runtime-deterministic-attempt-receipt/v1",
                "project": self.project,
                "task_id": task_id,
                "work_item_id": work_item_id,
                "attempt_id": attempt_id,
                "role": binding["role"],
                "worker": "agentlab-protocol-projector",
                "provider": "agentlab-deterministic",
                "status": "pass",
                "output_path": output_path.relative_to(task_root).as_posix(),
                "output_sha256": output_sha256,
                "sealed_sources": [
                    {
                        "path": path.relative_to(self.agentlab_root).as_posix(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in source_paths
                ],
                "deterministic_tool": tool,
                "model_execution": None,
            },
        )
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
        projection = self.runtime._transition_deterministic_attempt(
            task_id,
            attempt_id=attempt_id,
            idempotency_key=f"{idempotency_key}-succeeded",
            outcome={
                "execution_origin": "deterministic_tool_executor",
                "receipt_path": receipt_path.relative_to(task_root).as_posix(),
                "receipt_sha256": receipt_sha256,
                "output_sha256": output_sha256,
            },
        )
        return {
            "projection": projection,
            "output_path": str(output_path),
            "receipt_path": str(receipt_path),
        }


def prepare_protocol_task_if_present(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
) -> dict[str, Any] | None:
    """Prepare a protocol-bound Task, or return ``None`` for legacy-only tasks."""

    runner = ProductionProtocolRunner(agentlab_root, project=project)
    try:
        projection = runner.runtime.load_task(task_id)
    except LedgerIntegrityError as exc:
        if "has no TASK_CREATED event" in str(exc):
            return None
        raise
    except EntityNotFound:
        return None
    if not projection["task"].get("protocol_ref"):
        return None
    return runner.prepare(task_id)


def _nonempty_string(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"production protocol {field} is required")
    return normalized


def _document_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _professional_profiles(root: Path) -> Mapping[str, Any]:
    authority = safe_read_yaml(root / "config" / "agent_model_profiles.yml", default={})
    profiles = (
        authority.get("professional_role_profiles")
        if isinstance(authority, Mapping)
        else None
    )
    if not isinstance(profiles, Mapping):
        raise ValueError("professional role profile authority is unavailable")
    return profiles


def _bind_execution_profiles(
    root: Path, bindings: tuple[RoleBinding, ...]
) -> tuple[RoleBinding, ...]:
    professional_profiles = _professional_profiles(root)
    model_authority = safe_read_yaml(
        root / "config" / "agent_model_profiles.yml", default={}
    )
    tier_definitions = (
        (model_authority.get("tier_policy") or {}).get("tiers")
        if isinstance(model_authority, Mapping)
        else None
    )
    if not isinstance(tier_definitions, Mapping):
        raise ValueError("Agent model tier authority is unavailable")
    authority = safe_read_yaml(
        root / "config" / "production_role_profiles.yml", default={}
    )
    production_profiles = (
        authority.get("profiles") if isinstance(authority, Mapping) else None
    )
    if not isinstance(production_profiles, Mapping):
        raise ValueError("production role profile authority is unavailable")
    resolved: list[RoleBinding] = []
    for binding in bindings:
        if binding.profile is None:
            resolved.append(
                RoleBinding(
                    node_id=binding.node_id,
                    role=binding.role,
                    profile=None,
                    agent_model_profile=None,
                    execution_kind="cli_agent",
                    depends_on=binding.depends_on,
                )
            )
            continue
        profile = professional_profiles.get(binding.profile)
        if isinstance(profile, Mapping):
            base_role = profile.get("base_role_key")
            model_profile = binding.profile
        else:
            profile = production_profiles.get(binding.profile)
            if not isinstance(profile, Mapping):
                raise ValueError(f"unknown production role profile: {binding.profile}")
            base_role = normalize_role_key(str(profile.get("role") or ""))
            model_profile = _nonempty_string(
                profile.get("agent_model_profile"),
                field=f"profile {binding.profile} agent_model_profile",
            )
            registered_model_profiles = {str(tier).lower() for tier in tier_definitions}
            registered_model_profiles.update(
                str(alias).lower()
                for definition in tier_definitions.values()
                if isinstance(definition, Mapping)
                for alias in definition.get("budget_aliases") or []
            )
            if model_profile.lower() not in registered_model_profiles:
                raise ValueError(f"unknown Agent model profile: {model_profile}")
        if base_role != normalize_role_key(binding.role):
            raise ValueError(
                f"production role profile/base role mismatch: {binding.profile}"
            )
        resolved.append(
            RoleBinding(
                node_id=binding.node_id,
                role=binding.role,
                profile=binding.profile,
                agent_model_profile=model_profile,
                execution_kind=str(profile.get("execution_kind") or "cli_agent"),
                depends_on=binding.depends_on,
            )
        )
    return tuple(resolved)


def _protocol_pack(
    root: Path, protocol_ref: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    catalog = safe_read_yaml(root / "config" / "production_packs.yml", default={})
    packs = catalog.get("packs") if isinstance(catalog, Mapping) else None
    if not isinstance(packs, list):
        raise ValueError("production pack catalog is unavailable")
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw_pack in packs:
        if not isinstance(raw_pack, dict):
            continue
        protocol = raw_pack.get("protocol")
        if isinstance(protocol, dict) and protocol.get("ref") == protocol_ref:
            matches.append((raw_pack, protocol))
    if len(matches) != 1:
        qualifier = "unknown" if not matches else "ambiguous"
        raise ValueError(f"{qualifier} production protocol: {protocol_ref}")
    return matches[0]


def _static_role_bindings(protocol: Mapping[str, Any]) -> tuple[RoleBinding, ...]:
    raw_bindings = protocol.get("role_bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise ValueError("production protocol role_bindings must be non-empty")
    bindings: list[RoleBinding] = []
    known_nodes: set[str] = set()
    for raw in raw_bindings:
        if not isinstance(raw, Mapping):
            raise ValueError("production protocol role binding must be a mapping")
        node_id = _nonempty_string(raw.get("node_id"), field="role node_id")
        if node_id in known_nodes:
            raise ValueError(f"duplicate production protocol node: {node_id}")
        dependencies = tuple(str(item) for item in (raw.get("depends_on") or ()))
        unknown = sorted(set(dependencies) - known_nodes)
        if unknown:
            raise ValueError(
                f"production protocol node {node_id} has unknown or forward dependencies: "
                + ",".join(unknown)
            )
        bindings.append(
            RoleBinding(
                node_id=node_id,
                role=_nonempty_string(raw.get("role"), field="role"),
                profile=(str(raw["profile"]).strip() if raw.get("profile") else None),
                agent_model_profile=None,
                execution_kind=None,
                depends_on=dependencies,
            )
        )
        known_nodes.add(node_id)
    return tuple(bindings)


def _artifact_contracts(
    protocol: Mapping[str, Any],
    *,
    known_nodes: set[str],
) -> tuple[ArtifactContract, ...]:
    contracts: list[ArtifactContract] = []
    for raw in protocol.get("artifact_contracts") or ():
        if not isinstance(raw, Mapping):
            raise ValueError("production protocol artifact contract must be a mapping")
        producer = _nonempty_string(
            raw.get("producer_node"), field="artifact producer_node"
        )
        if producer not in known_nodes:
            raise ValueError(
                f"artifact contract references unknown producer node: {producer}"
            )
        contracts.append(
            ArtifactContract(
                artifact_type=_nonempty_string(
                    raw.get("artifact_type"), field="artifact_type"
                ),
                producer_node=producer,
                candidate_only=bool(raw.get("candidate_only", True)),
            )
        )
    if not contracts:
        raise ValueError("production protocol artifact_contracts must be non-empty")
    return tuple(contracts)


def _promotion_gate_bindings(
    protocol: Mapping[str, Any],
    *,
    gates: tuple[str, ...],
    known_nodes: set[str],
) -> tuple[PromotionGateBinding, ...]:
    raw_bindings = protocol.get("promotion_gate_bindings")
    if not isinstance(raw_bindings, Mapping):
        raise ValueError(
            "production protocol promotion_gate_bindings must be a mapping"
        )
    if set(raw_bindings) != set(gates):
        raise ValueError("production protocol promotion gate bindings are incomplete")
    bindings: list[PromotionGateBinding] = []
    for gate_id in gates:
        raw = raw_bindings.get(gate_id)
        if not isinstance(raw, Mapping):
            raise ValueError(f"promotion gate binding is invalid: {gate_id}")
        work_item_id = _nonempty_string(
            raw.get("work_item_id"), field=f"gate {gate_id} work_item_id"
        )
        evidence_kind = _nonempty_string(
            raw.get("evidence_kind"), field=f"gate {gate_id} evidence_kind"
        )
        if evidence_kind not in {"automated", "deterministic", "independent", "human"}:
            raise ValueError(f"promotion gate evidence kind is invalid: {gate_id}")
        if work_item_id not in known_nodes:
            raise ValueError(
                f"promotion gate {gate_id} references unknown node: {work_item_id}"
            )
        raw_subjects = raw.get("subject_artifact_types") or ()
        if isinstance(raw_subjects, str):
            raw_subjects = (raw_subjects,)
        subject_artifact_types = tuple(
            _nonempty_string(item, field=f"gate {gate_id} subject_artifact_type")
            for item in raw_subjects
        )
        if not subject_artifact_types:
            raise ValueError(
                f"promotion gate {gate_id} must bind subject artifact types"
            )
        bindings.append(
            PromotionGateBinding(
                gate_id,
                work_item_id,
                evidence_kind,
                subject_artifact_types,
            )
        )
    return tuple(bindings)


def _source_fact_bindings(
    protocol: Mapping[str, Any], *, known_nodes: set[str], known_facts: set[str]
) -> dict[str, tuple[str, ...]]:
    raw_bindings = protocol.get("source_fact_bindings") or {}
    if not isinstance(raw_bindings, Mapping):
        raise ValueError("production protocol source_fact_bindings must be a mapping")
    bindings: dict[str, tuple[str, ...]] = {}
    for node_id, raw_facts in raw_bindings.items():
        if node_id not in known_nodes:
            raise ValueError(f"source fact binding references unknown node: {node_id}")
        if isinstance(raw_facts, str) or not isinstance(raw_facts, (list, tuple)):
            raise ValueError(f"source fact binding must be a list: {node_id}")
        facts = tuple(_nonempty_string(item, field="source fact") for item in raw_facts)
        unknown = sorted(set(facts) - known_facts)
        if unknown:
            raise ValueError(
                f"source fact binding references unknown facts: {', '.join(unknown)}"
            )
        bindings[str(node_id)] = facts
    return bindings


def _validate_task_facts(
    protocol: Mapping[str, Any], task_facts: Mapping[str, Any]
) -> None:
    required = tuple(str(field) for field in (protocol.get("required_facts") or ()))
    optional = tuple(str(field) for field in (protocol.get("optional_facts") or ()))
    missing = sorted(
        field
        for field in required
        if field not in task_facts or task_facts.get(field) is None
    )
    if missing:
        raise ValueError("required task facts: " + ", ".join(missing))
    unknown = sorted(set(task_facts) - set(required) - set(optional))
    if unknown:
        raise ValueError("unknown task facts: " + ", ".join(unknown))
    for field in (
        "kind",
        "scope",
        "canon_impact",
        "repository",
        "source_story_bible",
        "source_story_artifact",
    ):
        if field in task_facts and (
            not isinstance(task_facts[field], str) or not task_facts[field].strip()
        ):
            raise ValueError(
                f"production protocol fact {field} must be a non-empty string"
            )
    if "target_count" in task_facts and (
        isinstance(task_facts["target_count"], bool)
        or not isinstance(task_facts["target_count"], int)
        or task_facts["target_count"] < 1
    ):
        raise ValueError(
            "production protocol fact target_count must be a positive integer"
        )
    if "chapter" in task_facts and (
        isinstance(task_facts["chapter"], bool)
        or not isinstance(task_facts["chapter"], int)
        or task_facts["chapter"] < 1
    ):
        raise ValueError("production protocol fact chapter must be a positive integer")
    if "risk_flags" in task_facts and (
        not isinstance(task_facts["risk_flags"], list)
        or any(
            not isinstance(flag, str) or not flag.strip()
            for flag in task_facts["risk_flags"]
        )
    ):
        raise ValueError(
            "production protocol fact risk_flags must be a list of non-empty strings"
        )
    constraints = protocol.get("fact_constraints") or {}
    if not isinstance(constraints, Mapping):
        raise ValueError("production protocol fact_constraints must be a mapping")
    for field, allowed in constraints.items():
        if not isinstance(allowed, list) or not allowed:
            raise ValueError(f"production protocol fact constraint is invalid: {field}")
        if task_facts.get(field) not in allowed:
            raise ValueError(
                f"production protocol fact {field} must be one of: "
                + ", ".join(str(item) for item in allowed)
            )


def _narrative_role_bindings(
    root: Path,
    task_facts: Mapping[str, Any],
) -> tuple[RoleBinding, ...]:
    raw_risks = task_facts.get("risk_flags") or ()
    if isinstance(raw_risks, (str, bytes)) or not isinstance(raw_risks, (list, tuple)):
        raise ValueError("narrative risk_flags must be a list")
    contract = load_author_team_contract(root)
    selection = select_author_team(contract, risk_flags=tuple(raw_risks))
    if selection["status"] != "pass":
        raise ValueError(
            "narrative role selection is blocked: " + ",".join(selection["issues"])
        )
    active_roles = tuple(selection["active_roles"])
    active = set(active_roles)
    bindings: list[RoleBinding] = []
    for role_id in active_roles:
        profile = contract["roles"][role_id]
        dependencies = tuple(
            dependency
            for dependency in profile.get("dependencies") or ()
            if dependency in active
        )
        missing = sorted(set(profile.get("dependencies") or ()) - active)
        if missing:
            raise ValueError(
                f"narrative role {role_id} has inactive dependencies: "
                + ",".join(missing)
            )
        bindings.append(
            RoleBinding(
                node_id=role_id,
                role=_nonempty_string(profile.get("extends_agent_role"), field="role"),
                profile=role_id,
                agent_model_profile=None,
                execution_kind=None,
                depends_on=dependencies,
            )
        )
    return tuple(bindings)


def compile_production_protocol(
    agentlab_root: Path,
    *,
    protocol_ref: str,
    task_facts: Mapping[str, Any],
) -> CompiledTaskGraph:
    """Compile one exact protocol ref without keyword routing or filesystem writes."""

    root = Path(agentlab_root).resolve()
    reference = _nonempty_string(protocol_ref, field="ref")
    if not isinstance(task_facts, Mapping):
        raise ValueError("task_facts must be a mapping")
    pack, protocol = _protocol_pack(root, reference)
    _validate_task_facts(protocol, task_facts)
    selection = str(protocol.get("role_selection") or "")
    if selection == "static":
        role_bindings = _static_role_bindings(protocol)
    elif selection == "narrative_author_team":
        role_bindings = _narrative_role_bindings(root, task_facts)
    else:
        raise ValueError(f"unsupported production protocol role selection: {selection}")
    role_bindings = _bind_execution_profiles(root, role_bindings)
    artifact_contracts = _artifact_contracts(
        protocol,
        known_nodes={binding.node_id for binding in role_bindings},
    )
    gates = tuple(str(gate) for gate in (protocol.get("promotion_gates") or ()))
    if not gates:
        raise ValueError("production protocol promotion_gates must be non-empty")
    gate_bindings = _promotion_gate_bindings(
        protocol,
        gates=gates,
        known_nodes={binding.node_id for binding in role_bindings},
    )
    known_facts = {
        str(item)
        for item in (
            *tuple(protocol.get("required_facts") or ()),
            *tuple(protocol.get("optional_facts") or ()),
        )
    }
    source_fact_bindings = _source_fact_bindings(
        protocol,
        known_nodes={binding.node_id for binding in role_bindings},
        known_facts=known_facts,
    )
    result_artifact_type = _nonempty_string(
        protocol.get("result_artifact_type"), field="result_artifact_type"
    )
    artifact_types = {contract.artifact_type for contract in artifact_contracts}
    if result_artifact_type not in artifact_types:
        raise ValueError("result_artifact_type is not a declared artifact contract")
    for gate in gate_bindings:
        unknown_subjects = sorted(set(gate.subject_artifact_types) - artifact_types)
        if unknown_subjects:
            raise ValueError(
                f"promotion gate {gate.gate_id} references undeclared artifacts: "
                + ", ".join(unknown_subjects)
            )
    facts_document = json.dumps(
        dict(task_facts),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return CompiledTaskGraph(
        protocol_ref=reference,
        pack_id=_nonempty_string(pack.get("pack_id"), field="pack_id"),
        task_facts_sha256=hashlib.sha256(facts_document).hexdigest(),
        role_bindings=role_bindings,
        artifact_contracts=artifact_contracts,
        promotion_gates=gates,
        promotion_gate_bindings=gate_bindings,
        source_fact_bindings=source_fact_bindings,
        result_artifact_type=result_artifact_type,
    )
