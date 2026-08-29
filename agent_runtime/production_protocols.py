"""Compile versioned production-pack protocols from declared task facts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any, Callable, Mapping

import yaml

from agent_runtime.atomic_io import safe_read_yaml
from agent_runtime.atomic_io import atomic_write_text, atomic_write_yaml
from agent_runtime.narrative.author_team import (
    load_author_team_contract,
    select_author_team,
)
from agent_runtime.narrative.visual_detail_cards import (
    PACK_SCHEMA,
    compile_visual_detail_card_pack,
    load_visual_detail_spec,
    validate_visual_detail_card_pack,
    validate_visual_pack_runtime_provenance,
)
from agent_runtime.outbound_context import is_forbidden_source_path
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
    role_contract: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        document = {
            "node_id": self.node_id,
            "role": self.role,
            "profile": self.profile,
            "agent_model_profile": self.agent_model_profile,
            "execution_kind": self.execution_kind,
            "work_item_kind": _ROLE_KINDS.get(self.role, "production"),
            "title": f"{self.profile or self.role}: {self.node_id}",
            "depends_on": list(self.depends_on),
        }
        if self.role_contract:
            document["role_contract"] = {
                key: list(value) if isinstance(value, tuple) else value
                for key, value in self.role_contract.items()
            }
        return document


@dataclass(frozen=True)
class ArtifactContract:
    """One immutable candidate artifact expected from a protocol node."""

    artifact_type: str
    producer_node: str
    candidate_only: bool
    output_instructions: tuple[str, ...] = ()
    required_markers: tuple[str, ...] = ()
    minimum_bytes: int = 1
    unique_content: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "producer_node": self.producer_node,
            "candidate_only": self.candidate_only,
            "output_instructions": list(self.output_instructions),
            "required_markers": list(self.required_markers),
            "minimum_bytes": self.minimum_bytes,
            "unique_content": self.unique_content,
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
_PROTOCOL_SOURCE_ROOTS = {
    "production",
    "project_brain",
    "reset_manifests",
    "runtime",
}


def _protocol_role_contract_message(
    binding: Mapping[str, Any],
    artifact_contracts: list[Mapping[str, Any]],
) -> dict[str, str]:
    """Render the compiled professional contract into the exact model payload."""

    role_contract = binding.get("role_contract") or {}
    artifact_types = [str(item["artifact_type"]) for item in artifact_contracts]
    lines = [
        "PROTOCOL_ROLE_CONTRACT/v1",
        f"work_item_id: {binding['node_id']}",
        f"professional_profile: {binding.get('profile') or binding['role']}",
        "candidate_artifact_types: " + (", ".join(artifact_types) or "none"),
    ]
    if artifact_types:
        lines.append(
            "Return only the assigned candidate artifact; do not copy a predecessor artifact verbatim."
        )
    for label, key in (
        ("Duties", "professional_duties"),
        ("Acceptance rules", "acceptance_rules"),
        ("Forbidden actions", "forbidden_actions"),
    ):
        values = role_contract.get(key) or ()
        if values:
            lines.append(f"{label}:")
            lines.extend(f"- {value}" for value in values)
    instructions = [
        str(value)
        for contract in artifact_contracts
        for value in (contract.get("output_instructions") or ())
    ]
    if instructions:
        lines.append("Artifact-specific instructions:")
        lines.extend(f"- {value}" for value in instructions)
    markers = [
        str(value)
        for contract in artifact_contracts
        for value in (contract.get("required_markers") or ())
    ]
    if markers:
        lines.append("Required literal markers:")
        lines.extend(f"- {value}" for value in markers)
    return {"role": "user", "content": "\n".join(lines)}


def _artifact_output_issues(
    contract: Mapping[str, Any],
    output_text: str,
    *,
    existing_artifacts: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Apply deterministic, protocol-declared admission checks to one candidate."""

    artifact_type = str(contract["artifact_type"])
    raw = output_text.encode("utf-8")
    issues: list[str] = []
    minimum_bytes = max(1, int(contract.get("minimum_bytes") or 1))
    if len(raw) < minimum_bytes:
        issues.append(
            f"artifact_output_too_small:{artifact_type}:{len(raw)}<{minimum_bytes}"
        )
    folded = output_text.casefold()
    for marker in contract.get("required_markers") or ():
        if str(marker).casefold() not in folded:
            issues.append(f"artifact_required_marker_missing:{artifact_type}:{marker}")
    if contract.get("unique_content"):
        digest = hashlib.sha256(raw).hexdigest()
        for artifact in existing_artifacts.values():
            if (
                artifact.get("artifact_id") != artifact_type
                and artifact.get("sha256") == digest
            ):
                issues.append(
                    "artifact_content_duplicates_existing_type:"
                    f"{artifact_type}:{artifact.get('artifact_id')}"
                )
                break
    return issues


class ProductionProtocolRunner:
    """Bind and materialize one protocol graph through the Task Runtime seam."""

    def __init__(
        self,
        agentlab_root: Path,
        *,
        project: str,
        role_executor_factory: Callable[[Path, str], Any] | None = None,
        runtime: TaskRuntime | None = None,
    ):
        self.agentlab_root = Path(agentlab_root).resolve()
        self.project = str(project)
        if runtime is not None and (
            runtime.agentlab_root != self.agentlab_root
            or runtime.project != self.project
        ):
            raise ValueError("injected TaskRuntime does not match the protocol runner")
        self.runtime = runtime or TaskRuntime(
            self.agentlab_root,
            project=self.project,
        )
        self._role_executor_factory = role_executor_factory

    def prepare(self, task_id: str) -> dict[str, Any]:
        """Compile and atomically materialize missing protocol WorkItems."""

        projection = self.runtime.load_task(task_id)
        task = projection["task"]
        protocol_ref = str(task.get("protocol_ref") or "")
        task_facts = task.get("input_profile")
        if not protocol_ref or not isinstance(task_facts, Mapping):
            raise InvalidTransition("Task is not bound to protocol facts")
        existing_graph = task.get("compiled_protocol")
        if existing_graph is None:
            graph = compile_production_protocol(
                self.agentlab_root,
                protocol_ref=protocol_ref,
                task_facts=task_facts,
            )
            graph_document = graph.as_dict()
            projection = self.runtime.bind_compiled_protocol(
                task_id,
                compiled_graph=graph_document,
                idempotency_key=f"protocol-{graph.task_facts_sha256[:24]}",
            )
        else:
            # Long-running tasks execute the immutable graph already committed
            # to their ledger. Configuration upgrades apply only to newly
            # compiled tasks and must not strand an in-flight production run.
            graph_document = dict(existing_graph)

        bindings = list(graph_document.get("role_bindings") or ())
        expected_ids = [str(binding["node_id"]) for binding in bindings]
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
            for binding in bindings:
                node_id = str(binding["node_id"])
                role = str(binding["role"])
                profile = binding.get("profile")
                item = existing_items[node_id]
                expected = {
                    "job_id": "job-main",
                    "kind": _ROLE_KINDS.get(role, "production"),
                    "title": f"{profile or role}: {node_id}",
                    "depends_on": list(binding.get("depends_on") or ()),
                    "protocol_role": role,
                    "protocol_profile": profile,
                    "agent_model_profile": binding.get("agent_model_profile"),
                    "execution_kind": binding.get("execution_kind"),
                }
                if any(item.get(field) != value for field, value in expected.items()):
                    raise InvalidTransition(
                        f"materialized protocol node is stale: {node_id}"
                    )
            return projection

        items = [
            {
                "job_id": "job-main",
                "work_item_id": str(binding["node_id"]),
                "kind": _ROLE_KINDS.get(str(binding["role"]), "production"),
                "title": f"{binding.get('profile') or binding['role']}: {binding['node_id']}",
                "depends_on": list(binding.get("depends_on") or ()),
                "requires_user_acceptance": False,
                "protocol_role": str(binding["role"]),
                "protocol_profile": binding.get("profile"),
                "agent_model_profile": binding.get("agent_model_profile"),
                "execution_kind": binding.get("execution_kind"),
            }
            for binding in bindings
        ]
        facts_sha256 = str(graph_document.get("task_facts_sha256") or "")
        return self.runtime.create_work_items(
            task_id,
            batch_id=f"protocol-{facts_sha256[:24]}",
            items=items,
            idempotency_key=f"materialize-{facts_sha256[:24]}",
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
        if (
            compiled.get("protocol_ref") == "narrative.visual.reference.v1"
            and work_item_id == "generation"
        ):
            raise InvalidTransition(
                "visual identity generation requires the governed managed-imagegen "
                "ingest adapter"
            )
        node_artifact_contracts = [
            contract
            for contract in compiled["artifact_contracts"]
            if contract["producer_node"] == work_item_id
        ]
        # Resolve and validate every declared source before emitting lifecycle
        # events. A missing or unsafe source is an admission failure, not a
        # started WorkItem, and must therefore leave the projection unchanged.
        governed_sources = self._governed_sources(
            task_id,
            projection=projection,
            binding=binding,
            source_paths=source_paths,
        )
        deterministic_preflight = self._deterministic_preflight(
            task_id,
            projection=projection,
            binding=binding,
            source_paths=governed_sources,
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
        reopen_history = (
            projection["work_items"][work_item_id].get("reopen_history") or []
        )
        last_reopened_at = (
            str(reopen_history[-1].get("recorded_at") or "") if reopen_history else ""
        )
        successful_attempts = [
            (existing_id, existing)
            for existing_id, existing in projection["attempts"].items()
            if existing.get("work_item_id") == work_item_id
            and existing.get("status") == "succeeded"
            and str(existing.get("updated_at") or "") > last_reopened_at
            and (attempt_id is None or existing_id == attempt_id)
        ]
        succeeded = successful_attempts[-1] if successful_attempts else None
        if succeeded is None:
            from agent_runtime.task_runtime_v2.role_executor import (
                RoleAttemptExecutor,
            )

            resolved_attempt_id = attempt_id or f"attempt-{work_item_id}-001"
            if self._is_deterministic_binding(binding):
                result = self._execute_deterministic_node(
                    task_id,
                    work_item_id=work_item_id,
                    attempt_id=resolved_attempt_id,
                    binding=binding,
                    source_paths=governed_sources,
                    preflight=deterministic_preflight,
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
                    messages=[
                        _protocol_role_contract_message(
                            binding,
                            node_artifact_contracts,
                        ),
                        *messages,
                    ],
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
        validation_issues = [
            issue
            for contract in node_artifact_contracts
            for issue in _artifact_output_issues(
                contract,
                output_text,
                existing_artifacts=projection["artifacts"],
            )
        ]
        validation_path = (
            self.runtime._task_dir(task_id)
            / "attempt_logs"
            / resolved_attempt_id
            / "artifact_validation_receipt.yml"
        )
        validation_status = "fail" if validation_issues else "pass"
        if attempt.get("output_validation") is None:
            atomic_write_yaml(
                validation_path,
                {
                    "schema_version": "protocol-artifact-validation/v1",
                    "status": validation_status,
                    "task_id": task_id,
                    "work_item_id": work_item_id,
                    "attempt_id": resolved_attempt_id,
                    "output_sha256": hashlib.sha256(
                        output_path.read_bytes()
                    ).hexdigest(),
                    "issues": validation_issues,
                },
            )
            projection = self.runtime.record_attempt_output_validation(
                task_id,
                attempt_id=resolved_attempt_id,
                status=validation_status,
                validation_receipt_path=validation_path,
                issues=validation_issues,
                idempotency_key=f"{idempotency_key}-output-validation",
            )
            attempt = projection["attempts"][resolved_attempt_id]
        elif attempt["output_validation"].get("status") != validation_status:
            raise InvalidTransition("Attempt output validation has drifted")
        if validation_issues:
            return {
                "status": "artifact_rejected",
                "work_item_id": work_item_id,
                "attempt_id": resolved_attempt_id,
                "issues": validation_issues,
                "projection": projection,
            }
        for contract in node_artifact_contracts:
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

        if (
            compiled.get("protocol_ref") == "narrative.visual.v1"
            and "visual_detail_cards_hash_verified" not in projection["protocol_gates"]
        ):
            visual_versions = [
                (version_id, artifact)
                for version_id, artifact in projection["artifacts"].items()
                if artifact.get("artifact_id") == "visual_detail_card_pack"
                and artifact.get("producer_attempt_id") == resolved_attempt_id
            ]
            if len(visual_versions) != 1:
                raise InvalidTransition(
                    "visual hash gate requires exactly one produced card pack"
                )
            visual_version_id, visual_artifact = visual_versions[0]
            projection = self.runtime.record_protocol_gate(
                task_id,
                gate_id="visual_detail_cards_hash_verified",
                work_item_id=work_item_id,
                evidence_kind="deterministic",
                evidence_sha256=_document_sha256(
                    {"visual_detail_card_pack": visual_artifact["sha256"]}
                ),
                attempt_id=resolved_attempt_id,
                subject_version_ids=[visual_version_id],
                actor="agentlab-visual-card-validator",
                idempotency_key=f"{idempotency_key}-gate-visual-hash",
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
            source_candidate = next(
                (candidate for candidate in candidates if candidate.exists()),
                None,
            )
            if source_candidate is None:
                raise InvalidTransition(
                    f"compiled protocol source fact is unavailable: {fact_name}"
                )
            if not Path(os.path.abspath(source_candidate)).is_relative_to(
                self.agentlab_root
            ):
                raise InvalidTransition(
                    "compiled protocol source fact is outside the AgentLab root: "
                    f"{fact_name}"
                )
            if _has_symlink_ancestry(source_candidate, self.agentlab_root):
                raise InvalidTransition(
                    f"compiled protocol source fact is unavailable: {fact_name}"
                )
            source_root = source_candidate.resolve(strict=True)
            if is_forbidden_source_path(source_root):
                raise InvalidTransition(
                    f"compiled protocol source fact is sensitive: {fact_name}"
                )
            if not source_root.is_relative_to(self.agentlab_root):
                raise InvalidTransition(
                    "compiled protocol source fact is outside the AgentLab root: "
                    f"{fact_name}"
                )
            expected_source_hash = str(facts.get(f"{fact_name}_sha256") or "")
            if expected_source_hash and (
                not source_root.is_file()
                or not re.fullmatch(r"[0-9a-f]{64}", expected_source_hash)
                or hashlib.sha256(source_root.read_bytes()).hexdigest()
                != expected_source_hash
            ):
                raise InvalidTransition(
                    f"compiled protocol source fact hash mismatch: {fact_name}"
                )
            project_root = (self.agentlab_root / "projects" / self.project).resolve(
                strict=True
            )
            try:
                relative_source_root = source_root.relative_to(project_root)
            except ValueError as exc:
                hash_fact_name = f"{fact_name}_sha256"
                expected_hash = str(facts.get(hash_fact_name) or "")
                observed_hash = (
                    hashlib.sha256(source_root.read_bytes()).hexdigest()
                    if source_root.is_file()
                    else ""
                )
                if (
                    not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
                    or observed_hash != expected_hash
                ):
                    raise InvalidTransition(
                        "compiled protocol source fact is outside its Project "
                        f"without a matching immutable hash: {fact_name}"
                    ) from exc
                governed.append(source_root)
                continue
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
            dependency_artifacts = [
                task_root / str(artifact["path"])
                for artifact in projection["artifacts"].values()
                if artifact.get("producer_attempt_id") == attempt_id
                and artifact.get("disposition", "eligible") == "eligible"
            ]
            if dependency_artifacts:
                governed.extend(dependency_artifacts)
            else:
                governed.append(task_root / "attempt_logs" / attempt_id / "output.md")
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
            and artifact.get("disposition", "eligible") == "eligible"
        )
        if compiled.get("protocol_ref") == "narrative.chapter.v1":
            self._validate_visual_prose_prerequisite(
                projection["task"].get("input_profile") or {}
            )
        deduplicated: list[Path] = []
        seen: set[Path] = set()
        for path in governed:
            if is_forbidden_source_path(path):
                raise InvalidTransition("compiled protocol source is sensitive")
            resolved = path.resolve(strict=True)
            if resolved not in seen:
                deduplicated.append(resolved)
                seen.add(resolved)
        return deduplicated

    def _validate_visual_prose_prerequisite(
        self,
        facts: Mapping[str, Any],
    ) -> None:
        """Require an exact hash-verified visual pack before prose starts."""

        visual_task_id = str(facts.get("source_visual_task_id") or "")
        version_id = str(facts.get("source_visual_pack_version_id") or "")
        try:
            visual = self.runtime.load_task(visual_task_id)
        except (EntityNotFound, LedgerIntegrityError) as exc:
            raise InvalidTransition("source visual Task is unavailable") from exc
        artifact = visual["artifacts"].get(version_id)
        gate = visual["protocol_gates"].get("visual_detail_cards_hash_verified")
        if (
            visual["task"].get("protocol_ref") != "narrative.visual.v1"
            or not isinstance(artifact, Mapping)
            or artifact.get("artifact_id") != "visual_detail_card_pack"
            or artifact.get("disposition", "eligible") != "eligible"
            or artifact.get("sha256") != facts.get("source_visual_detail_pack_sha256")
            or not isinstance(gate, Mapping)
            or gate.get("status") != "pass"
            or version_id not in (gate.get("subject_version_ids") or [])
        ):
            raise InvalidTransition(
                "prose requires an exact hash-verified visual detail card ArtifactVersion"
            )
        task_root = self.runtime._task_dir(visual_task_id)
        artifact_path = task_root / str(artifact.get("path") or "")
        declared = Path(str(facts.get("source_visual_detail_pack") or ""))
        declared_path = (
            declared if declared.is_absolute() else self.agentlab_root / declared
        )
        try:
            artifact_bytes = artifact_path.read_bytes()
            declared_resolved = declared_path.resolve(strict=True)
        except OSError as exc:
            raise InvalidTransition(
                "source visual ArtifactVersion is unavailable"
            ) from exc
        if declared_resolved != artifact_path.resolve(strict=True) or hashlib.sha256(
            artifact_bytes
        ).hexdigest() != artifact.get("sha256"):
            raise InvalidTransition(
                "source visual ArtifactVersion hash or path drifted"
            )
        try:
            pack = yaml.safe_load(artifact_bytes.decode("utf-8")) or {}
        except (UnicodeError, yaml.YAMLError) as exc:
            raise InvalidTransition(
                "source visual ArtifactVersion is unreadable"
            ) from exc
        pack_validation = validate_visual_detail_card_pack(pack)
        if (
            pack.get("schema_version") != PACK_SCHEMA
            or pack_validation["status"] != "pass"
        ):
            raise InvalidTransition("source visual ArtifactVersion is invalid")
        try:
            validate_visual_pack_runtime_provenance(
                self.agentlab_root,
                pack,
                artifact_path,
            )
        except ValueError as exc:
            raise InvalidTransition(
                "source visual ArtifactVersion provenance is invalid"
            ) from exc

    def _deterministic_preflight(
        self,
        task_id: str,
        *,
        projection: Mapping[str, Any],
        binding: Mapping[str, Any],
        source_paths: list[Path],
    ) -> dict[str, Any] | None:
        """Compile deterministic inputs before any Task or Attempt starts."""

        if projection["task"].get(
            "protocol_ref"
        ) != "narrative.visual.v1" or not self._is_deterministic_binding(binding):
            return None
        facts = projection["task"].get("input_profile") or {}
        raw_source = Path(str(facts.get("source_visual_detail_spec") or ""))
        candidates = (
            [raw_source]
            if raw_source.is_absolute()
            else [
                self.agentlab_root / raw_source,
                self.agentlab_root / "projects" / self.project / raw_source,
            ]
        )
        declared_source = next(
            (candidate for candidate in candidates if candidate.exists()),
            None,
        )
        if declared_source is None or _has_symlink_ancestry(
            declared_source,
            self.agentlab_root,
        ):
            raise InvalidTransition("visual detail spec is not a governed source")
        resolved_source = declared_source.resolve(strict=True)
        if resolved_source not in {path.resolve(strict=True) for path in source_paths}:
            raise InvalidTransition("visual detail spec is not a governed source")
        try:
            spec, sealed_sources = load_visual_detail_spec(
                self.agentlab_root,
                project=self.project,
                task_id=task_id,
                source_path=declared_source,
            )
            output_document = compile_visual_detail_card_pack(spec)
        except (OSError, ValueError) as exc:
            raise InvalidTransition(f"visual detail spec is invalid: {exc}") from exc
        if sealed_sources[0]["sha256"] != facts.get("source_visual_detail_spec_sha256"):
            raise InvalidTransition(
                "visual detail spec no longer matches its Task fact hash"
            )
        validation = validate_visual_detail_card_pack(output_document)
        if validation["status"] != "pass":
            raise InvalidTransition(
                "visual detail card compiler produced an invalid pack: "
                + ", ".join(validation["issues"])
            )
        blueprint_task_id = str(facts.get("source_blueprint_task_id") or "")
        blueprint_version_id = str(
            facts.get("source_blueprint_artifact_version_id") or ""
        )
        try:
            blueprint_projection = self.runtime.load_task(blueprint_task_id)
        except (EntityNotFound, LedgerIntegrityError) as exc:
            raise InvalidTransition("source blueprint Task is unavailable") from exc
        blueprint_artifact = blueprint_projection["artifacts"].get(blueprint_version_id)
        if (
            blueprint_projection["task"].get("protocol_ref") != "narrative.blueprint.v1"
            or not isinstance(blueprint_artifact, Mapping)
            or blueprint_artifact.get("artifact_id") != "story_blueprint"
            or blueprint_artifact.get("disposition", "eligible") != "eligible"
            or blueprint_artifact.get("sha256")
            != facts.get("source_blueprint_artifact_sha256")
        ):
            raise InvalidTransition(
                "source blueprint ArtifactVersion does not match the Task facts"
            )
        blueprint_path = self.runtime._task_dir(blueprint_task_id) / str(
            blueprint_artifact.get("path") or ""
        )
        try:
            blueprint_bytes = blueprint_path.read_bytes()
        except OSError as exc:
            raise InvalidTransition(
                "source blueprint ArtifactVersion is unavailable"
            ) from exc
        blueprint_sha256 = hashlib.sha256(blueprint_bytes).hexdigest()
        if blueprint_sha256 != blueprint_artifact.get("sha256"):
            raise InvalidTransition("source blueprint ArtifactVersion hash drifted")
        sealed_sources.append(
            {
                "path": blueprint_path.relative_to(self.agentlab_root).as_posix(),
                "sha256": blueprint_sha256,
            }
        )
        snapshot_sources = self._snapshot_visual_sources(
            task_id,
            sealed_sources,
        )
        return {
            "output_document": output_document,
            "declared_sources": sealed_sources,
            "sealed_sources": snapshot_sources,
        }

    def _snapshot_visual_sources(
        self,
        task_id: str,
        sources: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Copy verified bytes into immutable task-local preflight snapshots."""

        task_root = self.runtime._task_dir(task_id)
        snapshot_root = task_root / "inputs" / "snapshots"
        if _has_symlink_ancestry(snapshot_root, task_root):
            raise InvalidTransition("visual preflight snapshot path contains a symlink")
        snapshot_root.mkdir(parents=True, exist_ok=True)
        if (
            _has_symlink_ancestry(snapshot_root, task_root)
            or snapshot_root.resolve(strict=True)
            != task_root.resolve(strict=True) / "inputs" / "snapshots"
        ):
            raise InvalidTransition("visual preflight snapshot path escapes its Task")
        directory_flags = (
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(
                os,
                "O_NOFOLLOW",
                0,
            )
        )
        try:
            snapshot_dir_fd = os.open(snapshot_root, directory_flags)
        except OSError as exc:
            raise InvalidTransition(
                "visual preflight snapshot directory is unsafe"
            ) from exc
        snapshots: list[dict[str, str]] = []
        unique_sources: list[dict[str, str]] = []
        seen_sources: dict[str, str] = {}
        for source in sources:
            path_value = str(source.get("path") or "")
            digest = str(source.get("sha256") or "")
            previous = seen_sources.get(path_value)
            if previous is not None and previous != digest:
                raise InvalidTransition(
                    "visual preflight source path has conflicting hashes"
                )
            if previous is None:
                seen_sources[path_value] = digest
                unique_sources.append(source)
        try:
            for index, source in enumerate(unique_sources, start=1):
                digest = str(source.get("sha256") or "")
                original = self.agentlab_root / str(source.get("path") or "")
                try:
                    payload = original.read_bytes()
                except OSError as exc:
                    raise InvalidTransition(
                        "visual preflight source became unavailable"
                    ) from exc
                if hashlib.sha256(payload).hexdigest() != digest:
                    raise InvalidTransition(
                        "visual preflight source changed during snapshot"
                    )
                destination = snapshot_root / f"{index:03d}-{digest}.snapshot"
                temporary_name = f".{destination.name}.{uuid.uuid4().hex}.tmp"
                temporary_fd: int | None = None
                try:
                    temporary_fd = os.open(
                        temporary_name,
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | getattr(os, "O_NOFOLLOW", 0),
                        0o600,
                        dir_fd=snapshot_dir_fd,
                    )
                    with os.fdopen(temporary_fd, "wb") as handle:
                        temporary_fd = None
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    try:
                        os.link(
                            temporary_name,
                            destination.name,
                            src_dir_fd=snapshot_dir_fd,
                            dst_dir_fd=snapshot_dir_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        existing_fd = os.open(
                            destination.name,
                            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
                            dir_fd=snapshot_dir_fd,
                        )
                        with os.fdopen(existing_fd, "rb") as existing:
                            if hashlib.sha256(existing.read()).hexdigest() != digest:
                                raise InvalidTransition(
                                    "visual preflight snapshot collision"
                                )
                except OSError as exc:
                    raise InvalidTransition(
                        "visual preflight snapshot write is unsafe"
                    ) from exc
                finally:
                    if temporary_fd is not None:
                        os.close(temporary_fd)
                    try:
                        os.unlink(temporary_name, dir_fd=snapshot_dir_fd)
                    except FileNotFoundError:
                        pass
                snapshots.append(
                    {
                        "path": destination.relative_to(self.agentlab_root).as_posix(),
                        "sha256": digest,
                    }
                )
        finally:
            os.close(snapshot_dir_fd)
        return snapshots

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
        preflight: Mapping[str, Any] | None,
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
        if projection["task"]["protocol_ref"] == "narrative.visual.v1":
            tool["compiler_id"] = "narrative_visual_detail_card_compiler"
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
        if projection["task"]["protocol_ref"] == "narrative.visual.v1":
            if not isinstance(preflight, Mapping):
                raise InvalidTransition("visual deterministic preflight is missing")
            output_document = deepcopy(dict(preflight["output_document"]))
            sealed_sources = list(preflight["sealed_sources"])
            declared_sources = list(preflight["declared_sources"])
        else:
            source_hashes = {
                path.relative_to(self.agentlab_root).as_posix(): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in source_paths
            }
            output_document = {
                "schema_version": "protocol-deterministic-projection/v1",
                "protocol_ref": projection["task"]["protocol_ref"],
                "task_id": task_id,
                "work_item_id": work_item_id,
                "profile": binding.get("profile"),
                "status": "candidate_only",
                "source_hashes": source_hashes,
                "artifact_inputs": artifact_inputs,
                "source_artifacts": artifact_inputs,
                "progress_cursor": {
                    "accepted_chapter_count": 0,
                    "next_chapter": 1,
                    "target_total_chapters": int(
                        (projection["task"].get("input_profile") or {}).get(
                            "target_count"
                        )
                        or 0
                    ),
                },
                "task_facts_sha256": projection["task"]["compiled_protocol"][
                    "task_facts_sha256"
                ],
            }
            sealed_sources = [
                {
                    "path": path.relative_to(self.agentlab_root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in source_paths
            ]
            declared_sources = sealed_sources
        atomic_write_yaml(output_path, output_document)
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
                "sealed_sources": sealed_sources,
                "declared_sources": declared_sources,
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


def _has_symlink_ancestry(path: Path, boundary: Path) -> bool:
    """Inspect lexical path components without resolving away symlinks."""

    boundary_root = boundary.resolve(strict=True)
    lexical = Path(os.path.abspath(path))
    try:
        relative = lexical.relative_to(boundary_root)
    except ValueError:
        return True
    cursor = boundary_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


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
                    role_contract=binding.role_contract,
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
                role_contract=binding.role_contract,
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
                output_instructions=tuple(
                    _nonempty_string(item, field="artifact output instruction")
                    for item in (raw.get("output_instructions") or ())
                ),
                required_markers=tuple(
                    _nonempty_string(item, field="artifact required marker")
                    for item in (raw.get("required_markers") or ())
                ),
                minimum_bytes=max(1, int(raw.get("minimum_bytes") or 1)),
                unique_content=bool(raw.get("unique_content", False)),
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
        "project",
        "repository",
        "source_creative_brief",
        "source_creative_brief_sha256",
        "source_story_bible",
        "source_story_artifact",
        "source_blueprint_task_id",
        "source_blueprint_artifact_version_id",
        "source_visual_detail_spec",
        "source_visual_task_id",
        "source_visual_pack_version_id",
        "source_visual_pack_sha256",
        "card_id",
        "identity_reference_prompt_sha256",
        "source_visual_detail_pack",
    ):
        if field in task_facts and (
            not isinstance(task_facts[field], str) or not task_facts[field].strip()
        ):
            raise ValueError(
                f"production protocol fact {field} must be a non-empty string"
            )
    if "source_creative_brief_sha256" in task_facts and not re.fullmatch(
        r"[0-9a-f]{64}", str(task_facts["source_creative_brief_sha256"])
    ):
        raise ValueError(
            "production protocol fact source_creative_brief_sha256 must be lowercase 64-hex"
        )
    if "source_visual_detail_spec_sha256" in task_facts and not re.fullmatch(
        r"[0-9a-f]{64}", str(task_facts["source_visual_detail_spec_sha256"])
    ):
        raise ValueError(
            "production protocol fact source_visual_detail_spec_sha256 must be lowercase 64-hex"
        )
    if "source_visual_detail_pack_sha256" in task_facts and not re.fullmatch(
        r"[0-9a-f]{64}", str(task_facts["source_visual_detail_pack_sha256"])
    ):
        raise ValueError(
            "production protocol fact source_visual_detail_pack_sha256 must be lowercase 64-hex"
        )
    for field in ("source_visual_pack_sha256", "identity_reference_prompt_sha256"):
        if field in task_facts and not re.fullmatch(
            r"[0-9a-f]{64}", str(task_facts[field])
        ):
            raise ValueError(
                f"production protocol fact {field} must be lowercase 64-hex"
            )
    if "source_blueprint_artifact_sha256" in task_facts and not re.fullmatch(
        r"[0-9a-f]{64}", str(task_facts["source_blueprint_artifact_sha256"])
    ):
        raise ValueError(
            "production protocol fact source_blueprint_artifact_sha256 must be lowercase 64-hex"
        )
    if "repository_sha256" in task_facts and not re.fullmatch(
        r"[0-9a-f]{64}", str(task_facts["repository_sha256"])
    ):
        raise ValueError(
            "production protocol fact repository_sha256 must be lowercase 64-hex"
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
                role_contract={
                    key: tuple(profile.get(key) or ())
                    if key
                    in {"professional_duties", "acceptance_rules", "forbidden_actions"}
                    else str(profile.get(key) or "")
                    for key in (
                        "input_schema",
                        "output_schema",
                        "professional_duties",
                        "acceptance_rules",
                        "forbidden_actions",
                    )
                },
            )
        )
    return tuple(bindings)


def _narrative_full_role_bindings(
    root: Path,
    task_facts: Mapping[str, Any],
) -> tuple[RoleBinding, ...]:
    """Select the registered full author team for series-level blueprint work."""

    forced_facts = dict(task_facts)
    risks = list(task_facts.get("risk_flags") or ())
    if "major_reveal" not in risks:
        risks.append("major_reveal")
    forced_facts["risk_flags"] = risks
    bindings = list(_narrative_role_bindings(root, forced_facts))
    for index, binding in enumerate(bindings):
        if binding.node_id != "state_projector":
            continue
        dependencies = tuple(
            dict.fromkeys((*binding.depends_on, "reader_simulation_panel"))
        )
        bindings[index] = RoleBinding(
            node_id=binding.node_id,
            role=binding.role,
            profile=binding.profile,
            agent_model_profile=binding.agent_model_profile,
            execution_kind=binding.execution_kind,
            depends_on=dependencies,
            role_contract=binding.role_contract,
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
    elif selection == "narrative_full_author_team":
        role_bindings = _narrative_full_role_bindings(root, task_facts)
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
