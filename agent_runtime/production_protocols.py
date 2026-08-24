"""Compile versioned production-pack protocols from declared task facts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from agent_runtime.atomic_io import safe_read_yaml
from agent_runtime.narrative.author_team import (
    load_author_team_contract,
    select_author_team,
)
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
    depends_on: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "profile": self.profile,
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
class CompiledTaskGraph:
    """Deterministic execution graph produced by one versioned protocol."""

    protocol_ref: str
    pack_id: str
    task_facts_sha256: str
    role_bindings: tuple[RoleBinding, ...]
    artifact_contracts: tuple[ArtifactContract, ...]
    promotion_gates: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "compiled-task-graph/v1",
            "protocol_ref": self.protocol_ref,
            "pack_id": self.pack_id,
            "task_facts_sha256": self.task_facts_sha256,
            "role_bindings": [binding.as_dict() for binding in self.role_bindings],
            "artifact_contracts": [contract.as_dict() for contract in self.artifact_contracts],
            "promotion_gates": list(self.promotion_gates),
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


class ProductionProtocolRunner:
    """Bind and materialize one protocol graph through the Task Runtime seam."""

    def __init__(self, agentlab_root: Path, *, project: str):
        self.agentlab_root = Path(agentlab_root).resolve()
        self.project = str(project)
        self.runtime = TaskRuntime(self.agentlab_root, project=self.project)

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
            raise InvalidTransition("Task protocol compilation no longer matches its ledger")

        expected_ids = [binding.node_id for binding in graph.role_bindings]
        existing_items = projection["work_items"]
        materialized = [node_id for node_id in expected_ids if node_id in existing_items]
        if materialized and len(materialized) != len(expected_ids):
            raise InvalidTransition("Task contains a partially materialized protocol graph")
        if materialized:
            for binding in graph.role_bindings:
                item = existing_items[binding.node_id]
                if item.get("depends_on") != list(binding.depends_on):
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
                "requires_user_acceptance": binding.node_id == "master_verification",
            }
            for binding in graph.role_bindings
        ]
        return self.runtime.create_work_items(
            task_id,
            batch_id=f"protocol-{graph.task_facts_sha256[:24]}",
            items=items,
            idempotency_key=f"materialize-{graph.task_facts_sha256[:24]}",
        )


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


def _protocol_pack(root: Path, protocol_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
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
        producer = _nonempty_string(raw.get("producer_node"), field="artifact producer_node")
        if producer not in known_nodes:
            raise ValueError(f"artifact contract references unknown producer node: {producer}")
        contracts.append(
            ArtifactContract(
                artifact_type=_nonempty_string(raw.get("artifact_type"), field="artifact_type"),
                producer_node=producer,
                candidate_only=bool(raw.get("candidate_only", True)),
            )
        )
    if not contracts:
        raise ValueError("production protocol artifact_contracts must be non-empty")
    return tuple(contracts)


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
    required = tuple(str(field) for field in (protocol.get("required_facts") or ()))
    missing = sorted(field for field in required if not task_facts.get(field))
    if missing:
        raise ValueError("required task facts: " + ", ".join(missing))
    selection = str(protocol.get("role_selection") or "")
    if selection == "static":
        role_bindings = _static_role_bindings(protocol)
    elif selection == "narrative_author_team":
        role_bindings = _narrative_role_bindings(root, task_facts)
    else:
        raise ValueError(f"unsupported production protocol role selection: {selection}")
    artifact_contracts = _artifact_contracts(
        protocol,
        known_nodes={binding.node_id for binding in role_bindings},
    )
    gates = tuple(str(gate) for gate in (protocol.get("promotion_gates") or ()))
    if not gates:
        raise ValueError("production protocol promotion_gates must be non-empty")
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
    )
