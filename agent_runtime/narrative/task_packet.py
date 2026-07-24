"""Compile append-only Runtime v2 work for governed narrative changes."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Mapping
import re

import yaml

from agent_runtime.artifact_digest import artifact_sha256
from agent_runtime.atomic_io import atomic_write_yaml
from agent_runtime.narrative.blueprint_lifecycle import (
    validate_project_blueprint,
)
from agent_runtime.narrative.blueprint_validation import validate_crown_blueprint
from agent_runtime.project_agents import (
    AgentContract,
    ProjectAgentRegistry,
    effective_contract_hash,
)
from agent_runtime.project_truth import ProjectTruthStore
from agent_runtime.task_runtime_v2 import TaskRuntime


_REQUEST_FIELDS = frozenset(
    {
        "change_kind",
        "requested_delta",
        "target_scope",
        "preserve_invariants",
        "allowed_retcons",
        "acceptance_rules",
        "idempotency_key",
    }
)
_SAFE_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,96}")
_CHANGE_PROFILES = {
    "blueprint_change": {
        "kind": "structural_change",
        "scope": "cross_artifact",
        "canon_impact": "canonical",
        "risk_flags": ["longform_continuity", "world_model_change"],
        "candidate_leaf": "blueprint_change_set.yml",
        "producer_id": "artifact-producer",
        "producer_kind": "blueprint",
        "producer_title": "Produce blueprint change set",
    },
    "global_character_change": {
        "kind": "consistency_patch",
        "scope": "cross_artifact",
        "canon_impact": "canonical",
        "risk_flags": ["longform_continuity", "relationship_continuity"],
        "candidate_leaf": "character_change_set.yml",
        "producer_id": "artifact-producer",
        "producer_kind": "character-change",
        "producer_title": "Produce global character change set",
    },
    "chapter_revision": {
        "kind": "creative_patch",
        "scope": "multi_chapter",
        "canon_impact": "candidate",
        "risk_flags": ["longform_continuity"],
        "candidate_leaf": "manuscript_candidate/",
        "producer_id": "writer",
        "producer_kind": "prose",
        "producer_title": "Write revised chapter candidate",
    },
    "new_chapter": {
        "kind": "prose_build",
        "scope": "multi_chapter",
        "canon_impact": "candidate",
        "risk_flags": ["longform_continuity"],
        "candidate_leaf": "manuscript_candidate/",
        "producer_id": "writer",
        "producer_kind": "prose",
        "producer_title": "Write new chapter candidate",
    },
}


def _validated_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("narrative request must be a mapping")
    request = dict(raw)
    missing = sorted(_REQUEST_FIELDS - set(request))
    unknown = sorted(set(request) - _REQUEST_FIELDS)
    if missing or unknown:
        raise ValueError(
            "narrative request fields mismatch"
            + (f"; missing={','.join(missing)}" if missing else "")
            + (f"; unknown={','.join(unknown)}" if unknown else "")
        )
    change_kind = str(request.get("change_kind") or "").strip()
    requested_delta = str(request.get("requested_delta") or "").strip()
    idempotency_key = str(request.get("idempotency_key") or "").strip()
    if change_kind not in _CHANGE_PROFILES:
        raise ValueError(f"unsupported narrative change_kind: {change_kind}")
    if (
        not requested_delta
        or not _SAFE_IDEMPOTENCY_KEY.fullmatch(idempotency_key)
    ):
        raise ValueError("requested_delta and idempotency_key are required")
    target_scope = request.get("target_scope")
    if not isinstance(target_scope, (str, list, dict)) or not target_scope:
        raise ValueError("target_scope must be a non-empty string, list, or mapping")
    for field in ("preserve_invariants", "allowed_retcons", "acceptance_rules"):
        values = request.get(field)
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not item.strip() for item in values
        ):
            raise ValueError(f"{field} must be a list of non-empty strings")
    if not request["acceptance_rules"]:
        raise ValueError("acceptance_rules must not be empty")
    request["change_kind"] = change_kind
    request["requested_delta"] = requested_delta
    request["idempotency_key"] = idempotency_key
    return request


def _target_count(target_scope: Any) -> int:
    if isinstance(target_scope, dict):
        for field in ("chapters", "artifacts", "characters"):
            values = target_scope.get(field)
            if isinstance(values, list) and values:
                return len(values)
    if isinstance(target_scope, list):
        return len(target_scope)
    return 1


def _work_items(profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    brain_plan = {
        "job_id": "job-main",
        "work_item_id": "brain-plan",
        "kind": "planning",
        "title": "Approve narrative scope and execution plan",
        "depends_on": [],
    }
    experts = [
        {
            "job_id": "job-main",
            "work_item_id": "world-architect",
            "kind": "expert-check",
            "title": "Validate world rules",
            "depends_on": ["brain-plan"],
        },
        {
            "job_id": "job-main",
            "work_item_id": "character-keeper",
            "kind": "expert-check",
            "title": "Validate character and relationship state",
            "depends_on": ["brain-plan"],
        },
        {
            "job_id": "job-main",
            "work_item_id": "timeline-keeper",
            "kind": "expert-check",
            "title": "Validate timeline state",
            "depends_on": ["brain-plan"],
        },
        {
            "job_id": "job-main",
            "work_item_id": "plot-mystery-keeper",
            "kind": "expert-check",
            "title": "Validate plot, mystery, and foreshadowing",
            "depends_on": ["brain-plan"],
        },
    ]
    producer_id = str(profile["producer_id"])
    producer = {
        "job_id": "job-main",
        "work_item_id": producer_id,
        "kind": str(profile["producer_kind"]),
        "title": str(profile["producer_title"]),
        "depends_on": [str(item["work_item_id"]) for item in experts],
    }
    return [
        brain_plan,
        *experts,
        producer,
        {
            "job_id": "job-main",
            "work_item_id": "reviewer",
            "kind": "quality-review",
            "title": "Review overall narrative quality",
            "depends_on": [producer_id],
        },
        {
            "job_id": "job-main",
            "work_item_id": "verifier",
            "kind": "verification",
            "title": "Verify hashes, continuity, and promotion readiness",
            "depends_on": ["reviewer"],
        },
    ]


def _bind_project_agents(
    root: Path,
    *,
    project: str,
    profile: Mapping[str, Any],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    project_root = root / "projects" / project
    manifest_path = project_root / "project.yml"
    if not manifest_path.is_file():
        return items
    if manifest_path.is_symlink():
        raise ValueError("project manifest must not be a symlink")
    try:
        project_manifest = yaml.safe_load(
            manifest_path.read_text(encoding="utf-8")
        ) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read project manifest: {exc}") from exc
    features = (
        project_manifest.get("features")
        if isinstance(project_manifest, dict)
        else {}
    ) or {}
    if features.get("enable_project_agents") is not True:
        return items

    truth = ProjectTruthStore(project_root)
    registry = ProjectAgentRegistry(truth)
    with truth.current_snapshot_lease() as current:
        manifests = {manifest.id: manifest for manifest in registry.list()}
        plot_agent_id = (
            "mystery_keeper" if "mystery_keeper" in manifests else "plot"
        )
        producer_agent_id = (
            "blueprint_producer"
            if profile["producer_id"] == "artifact-producer"
            else "writer"
        )
        agent_by_work_item = {
            "brain-plan": "supervisor",
            "world-architect": "world",
            "character-keeper": "character",
            "timeline-keeper": "timeline",
            "plot-mystery-keeper": plot_agent_id,
            str(profile["producer_id"]): producer_agent_id,
            "reviewer": "reviewer",
            "verifier": "checker",
        }
        bound: list[dict[str, Any]] = []
        for item in items:
            work_item_id = str(item["work_item_id"])
            agent_id = agent_by_work_item.get(work_item_id)
            manifest = manifests.get(str(agent_id or ""))
            if manifest is None:
                raise ValueError(
                    "enabled project Agent team is incomplete for narrative task: "
                    f"{work_item_id} requires {agent_id}"
                )
            AgentContract(manifest).assert_active()
            bound.append(
                {
                    **item,
                    "assigned_agent_id": manifest.id,
                    "agent_manifest_revision": manifest.manifest_revision,
                    "canonical_snapshot_id": current.snapshot_id,
                    "effective_contract_hash": effective_contract_hash(manifest),
                }
            )
    return bound


def _authoritative_task_packet(
    runtime: TaskRuntime,
    *,
    task_id: str,
) -> tuple[dict[str, Any], Path]:
    projection = runtime.load_task(task_id)
    records = [
        record
        for record in projection.get("trace_records", {}).values()
        if isinstance(record, dict)
        and record.get("record_type") == "narrative_task_packet"
    ]
    if len(records) != 1:
        raise ValueError("narrative Task requires one immutable task packet trace")
    record = records[0]
    record_relative = PurePosixPath(str(record.get("path") or ""))
    if (
        record_relative.is_absolute()
        or not record_relative.parts
        or record_relative.parts[0] != "records"
        or any(part in {"", ".", ".."} for part in record_relative.parts)
    ):
        raise ValueError("immutable narrative task packet path is invalid")
    task_root = runtime.tasks_root / task_id
    packet_path = task_root / Path(*record_relative.parts)
    cursor = task_root
    contains_symlink = task_root.is_symlink()
    for part in record_relative.parts:
        cursor = cursor / part
        contains_symlink = contains_symlink or cursor.is_symlink()
    if (
        contains_symlink
        or not packet_path.is_file()
        or artifact_sha256(packet_path) != record.get("sha256")
    ):
        raise ValueError("immutable narrative task packet bytes are missing or stale")
    try:
        packet = yaml.safe_load(packet_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read immutable narrative task packet: {exc}") from exc
    if (
        not isinstance(packet, dict)
        or packet != record.get("record_data")
        or packet.get("task_id") != task_id
    ):
        raise ValueError("immutable narrative task packet is invalid")
    return packet, packet_path


def _truth_bindings(
    root: Path,
    *,
    project: str,
) -> dict[str, Any]:
    project_root = root / "projects" / project
    authority_path = project_root / "production" / "blueprint_authority.yml"
    try:
        authority = yaml.safe_load(authority_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read blueprint authority: {exc}") from exc
    is_crown_profile = (
        isinstance(authority, dict)
        and authority.get("schema_version") == "crown-blueprint-authority/v1"
    )
    if is_crown_profile:
        detailed_range = (authority.get("scope") or {}).get(
            "detailed_chapter_contract_range"
        )
        if (
            not isinstance(detailed_range, list)
            or len(detailed_range) != 2
            or any(type(item) is not int for item in detailed_range)
        ):
            raise ValueError("Crown blueprint detailed chapter range is invalid")
        crown_validation = validate_crown_blueprint(
            root,
            project=project,
            chapter_start=detailed_range[0],
            chapter_end=detailed_range[1],
        )
        receipt_path = (
            project_root / "project_brain" / "blueprint_validation_receipt.yml"
        )
        try:
            seal_receipt = (
                yaml.safe_load(receipt_path.read_text(encoding="utf-8")) or {}
            )
        except (OSError, UnicodeError, yaml.YAMLError):
            seal_receipt = {}
        authority_sha256 = artifact_sha256(authority_path)
        artifact_hashes = (
            seal_receipt.get("artifact_hashes")
            if isinstance(seal_receipt, dict)
            else {}
        ) or {}
        sealed = (
            seal_receipt.get("status") == "pass"
            and artifact_hashes.get("production/blueprint_authority.yml")
            == authority_sha256
        )
        validation = {
            **crown_validation,
            "sealed": sealed,
            "authority_sha256": authority_sha256,
            "artifact_index_sha256": artifact_sha256(
                project_root / "project_artifact_index.yml"
            ),
        }
    else:
        validation = validate_project_blueprint(root, project=project)
    if validation["status"] != "pass" or validation["sealed"] is not True:
        raise ValueError(
            "narrative task requires one validated sealed blueprint: "
            + ", ".join(str(item) for item in validation["issues"])
        )
    fact_snapshot = project_root / "project_brain" / "project_fact_snapshot.yml"
    knowledge_snapshot_path = (
        project_root / "project_brain" / "knowledge_index_snapshot.yml"
    )
    try:
        knowledge_snapshot = (
            yaml.safe_load(knowledge_snapshot_path.read_text(encoding="utf-8")) or {}
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read project knowledge snapshot: {exc}") from exc
    if (
        not isinstance(knowledge_snapshot, dict)
        or knowledge_snapshot.get("status") != "sealed"
        or knowledge_snapshot.get("namespace") != f"project.{project}"
        or not str(knowledge_snapshot.get("index_snapshot") or "").strip()
    ):
        raise ValueError("project knowledge snapshot is missing or stale")
    indexed_hashes = knowledge_snapshot.get("indexed_source_hashes")
    manifest_path = project_root / "project.yml"
    try:
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        manifest = {}
    features = manifest.get("features") if isinstance(manifest, dict) else {}
    if (features or {}).get("project_truth_mode") == "enforced":
        truth = ProjectTruthStore(project_root)
        truth.audit()
        current = truth.current()
        pointer_path = project_root / "project_truth.yml"
        snapshot_path = (
            project_root
            / ".agentlab"
            / "truth"
            / "snapshots"
            / f"{current.snapshot_id}.yml"
        )
        expected_indexed_hashes = {
            f"projects/{project}/project_truth.yml": artifact_sha256(pointer_path),
            (
                f"projects/{project}/.agentlab/truth/snapshots/"
                f"{current.snapshot_id}.yml"
            ): artifact_sha256(snapshot_path),
        }
    else:
        expected_indexed_hashes = {
            f"projects/{project}/production/blueprint_authority.yml": validation[
                "authority_sha256"
            ],
            f"projects/{project}/production/narrative_modification_contract.yml": (
                artifact_sha256(
                    project_root
                    / "production"
                    / "narrative_modification_contract.yml"
                )
            ),
            f"projects/{project}/project_brain/project_fact_snapshot.yml": (
                artifact_sha256(fact_snapshot)
            ),
        }
    if not isinstance(indexed_hashes, dict) or any(
        indexed_hashes.get(path) != digest
        for path, digest in expected_indexed_hashes.items()
    ):
        raise ValueError(
            "project knowledge snapshot does not match current narrative truth"
        )
    source_artifacts = (
        authority.get("source_artifacts") if isinstance(authority, dict) else {}
    )
    manuscript = next(
        (
            item
            for item in (source_artifacts or {}).values()
            if isinstance(item, dict)
            and item.get("artifact_id") == "manuscript_series"
        ),
        {},
    )
    return {
        "blueprint_authority_sha256": validation["authority_sha256"],
        "project_artifact_index_sha256": validation["artifact_index_sha256"],
        "project_fact_snapshot_sha256": artifact_sha256(fact_snapshot),
        "knowledge_index_snapshot_sha256": artifact_sha256(
            knowledge_snapshot_path
        ),
        "knowledge_index_snapshot_id": knowledge_snapshot["index_snapshot"],
        "manuscript_series_sha256": manuscript.get("sha256"),
    }


def compile_narrative_task_packet(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Create one Runtime v2 Task, append its first prompt, and materialize its DAG."""

    root = Path(agentlab_root).resolve()
    normalized = _validated_request(request)
    profile = _CHANGE_PROFILES[normalized["change_kind"]]
    runtime = TaskRuntime(root, project=project)
    project = runtime.project
    bindings = _truth_bindings(root, project=project)
    items = _bind_project_agents(
        root,
        project=project,
        profile=profile,
        items=_work_items(profile),
    )
    user_goal = yaml.safe_dump(
        normalized,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()
    input_profile = {
        "kind": profile["kind"],
        "scope": profile["scope"],
        "target_count": _target_count(normalized["target_scope"]),
        "canon_impact": profile["canon_impact"],
        "risk_flags": list(profile["risk_flags"]),
    }
    runtime.create_task(
        task_id=task_id,
        title=f"{normalized['change_kind']}: {normalized['requested_delta'][:80]}",
        user_goal=user_goal,
        input_profile=input_profile,
        idempotency_key=f"narrative-task.{normalized['idempotency_key']}",
    )
    projection = runtime.append_instruction(
        task_id,
        instruction_id="instruction-001",
        requested_delta=normalized["requested_delta"],
        target_scope=normalized["target_scope"],
        preserve_invariants=normalized["preserve_invariants"],
        allowed_retcons=normalized["allowed_retcons"],
        acceptance_rules=normalized["acceptance_rules"],
        idempotency_key=f"narrative-instruction.{normalized['idempotency_key']}",
    )
    projection = runtime.create_work_items(
        task_id,
        batch_id="narrative-workflow",
        items=items,
        idempotency_key=f"narrative-workflow.{normalized['idempotency_key']}",
    )
    candidate_output = (
        f"runtime/tasks/{task_id}/artifacts/{profile['candidate_leaf']}"
    )
    packet = {
        "schema_version": "narrative-task-packet/v1",
        "status": "compiled",
        "runtime_standard": "task-runtime-v2",
        "project": project,
        "task_id": task_id,
        "change_kind": normalized["change_kind"],
        "request": normalized,
        "prompt_policy": {
            "append_only_task_events": True,
            "overwrite_old_prompt_forbidden": True,
        },
        "truth_bindings": bindings,
        "required_roles": [
            item["work_item_id"] for item in items
        ],
        "project_agent_bindings": {
            str(item["work_item_id"]): {
                key: item[key]
                for key in (
                    "assigned_agent_id",
                    "agent_manifest_revision",
                    "canonical_snapshot_id",
                    "effective_contract_hash",
                )
                if key in item
            }
            for item in items
        },
        "candidate_output": candidate_output,
        "instructions": projection["task"]["instructions"],
    }
    packet_path = (
        root
        / "projects"
        / project
        / "runtime"
        / "tasks"
        / task_id
        / "records"
        / "staging"
        / "narrative_task_packet.yml"
    )
    atomic_write_yaml(packet_path, packet, sort_keys=False)
    projection = runtime.record_trace(
        task_id,
        record_id="narrative-task-packet",
        record_type="narrative_task_packet",
        producer="agentlab",
        producer_role="Runtime",
        path=packet_path,
        idempotency_key=f"narrative-packet.{normalized['idempotency_key']}",
    )
    immutable_packet_path = (
        runtime.tasks_root
        / task_id
        / projection["trace_records"]["narrative-task-packet"]["path"]
    )
    return {
        "schema_version": "narrative-task-compile-result/v1",
        "status": "compiled",
        "runtime_standard": "task-runtime-v2",
        "project": project,
        "task_id": task_id,
        "packet_path": immutable_packet_path.relative_to(root).as_posix(),
        "candidate_output": candidate_output,
        "work_item_count": len(projection["work_items"]),
        "instruction_count": len(projection["task"]["instructions"]),
    }


def append_narrative_instruction(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    instruction_id: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Append a structured prompt to an existing narrative Task ledger."""

    root = Path(agentlab_root).resolve()
    normalized = _validated_request(request)
    runtime = TaskRuntime(root, project=project)
    packet, packet_path = _authoritative_task_packet(runtime, task_id=task_id)
    if packet.get("change_kind") != normalized["change_kind"]:
        raise ValueError(
            "appended narrative instruction must keep the Task change_kind"
        )
    current = _truth_bindings(root, project=project)
    if packet.get("truth_bindings") != current:
        raise ValueError(
            "narrative task truth bindings are stale; compile a replacement Task"
        )
    projection = runtime.load_task(task_id)
    non_packet_records = [
        record
        for record in projection.get("trace_records", {}).values()
        if record.get("record_type") != "narrative_task_packet"
    ]
    if (
        projection.get("attempts")
        or projection.get("artifacts")
        or projection.get("evidence_bindings")
        or non_packet_records
    ):
        raise ValueError(
            "narrative Task execution already started; compile a replacement Task"
        )
    projection = runtime.append_instruction(
        task_id,
        instruction_id=instruction_id,
        requested_delta=normalized["requested_delta"],
        target_scope=normalized["target_scope"],
        preserve_invariants=normalized["preserve_invariants"],
        allowed_retcons=normalized["allowed_retcons"],
        acceptance_rules=normalized["acceptance_rules"],
        idempotency_key=f"narrative-instruction.{normalized['idempotency_key']}",
    )
    return {
        "schema_version": "narrative-instruction-append-result/v1",
        "status": "appended",
        "project": project,
        "task_id": task_id,
        "instruction_id": instruction_id,
        "instruction_count": len(projection["task"]["instructions"]),
        "packet_path": packet_path.relative_to(root).as_posix(),
    }
