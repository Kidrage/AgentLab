"""Professional narrative team contracts and risk-bounded activation."""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
import fcntl
import hashlib
import re

import yaml

from atomic_io import atomic_write_yaml
from agent_runtime.knowledge_system.storage import KnowledgeStore
from agent_runtime.project_agents.contract import AgentContractViolation
from agent_runtime.project_agents.models import AgentManifest
from agent_runtime.project_agents.registry import ProjectAgentRegistry
from agent_runtime.project_truth.models import ChangeSet, ResourceChange
from agent_runtime.project_truth.store import ProjectTruthStore

REQUIRED_AUTHOR_ROLES = (
    "authorial_director",
    "canon_timeline_steward",
    "plot_causality_architect",
    "character_ensemble_director",
    "relationship_director",
    "world_archaeologist",
    "foreshadow_mystery_keeper",
    "arc_scene_planner",
    "research_style_curator",
    "writer",
    "senior_editor",
    "reader_simulation_panel",
    "state_projector",
)

_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
_TASK_ID = re.compile(r"^task_[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")

_REQUIRED_FIELDS = (
    "manifest_version",
    "professional_duties",
    "knowledge_namespaces",
    "input_schema",
    "output_schema",
    "tools",
    "runtime",
    "authority",
    "forbidden_actions",
    "dependencies",
    "acceptance_rules",
)


def _nonempty_strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _read_yaml_mapping(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return dict(value)


def _role_key(value: object) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", str(value or "")).lower()


def load_author_team_contract(
    agentlab_root: Path,
    *,
    composition_path: Path | None = None,
) -> dict[str, Any]:
    """Resolve one team contract from canonical role and model authorities."""

    root = Path(agentlab_root).resolve()
    selected = (
        Path(composition_path).resolve()
        if composition_path is not None
        else root / "config" / "narrative_author_team.yml"
    )
    try:
        selected.relative_to(root)
    except ValueError as exc:
        raise ValueError("author-team composition must be inside AgentLab root") from exc
    composition = _read_yaml_mapping(
        selected,
        label="author-team composition",
    )
    if composition.get("schema_version") != "narrative-author-team-composition/v1":
        raise ValueError("unsupported author-team composition schema")
    registry_path = root / "config" / "agent_registry.yml"
    model_path = root / "config" / "agent_model_profiles.yml"
    registry = _read_yaml_mapping(registry_path, label="agent registry")
    model_profiles = _read_yaml_mapping(
        model_path,
        label="agent model profiles",
    )
    profiles = registry.get("professional_profiles")
    base_agents = registry.get("agents")
    execution_profiles = model_profiles.get("professional_role_profiles")
    if not isinstance(profiles, Mapping) or not isinstance(base_agents, Mapping):
        raise ValueError("agent registry has no professional profile authority")
    if not isinstance(execution_profiles, Mapping):
        raise ValueError("model profiles have no professional role authority")
    role_ids = composition.get("roles")
    if (
        not isinstance(role_ids, list)
        or role_ids != list(REQUIRED_AUTHOR_ROLES)
    ):
        raise ValueError("author-team composition role order is invalid")
    resolved: dict[str, Any] = {}
    for role_id in role_ids:
        profile = profiles.get(role_id)
        if not isinstance(profile, Mapping):
            raise ValueError(f"professional role is not registered: {role_id}")
        runtime_ref = profile.get("runtime")
        runtime_ref = runtime_ref if isinstance(runtime_ref, Mapping) else {}
        model_ref = str(runtime_ref.get("model_profile_ref") or "")
        execution = execution_profiles.get(model_ref)
        if not isinstance(execution, Mapping):
            raise ValueError(f"professional model profile is missing: {model_ref}")
        base_role = str(profile.get("extends_agent_role") or "")
        if base_role not in base_agents:
            raise ValueError(f"professional base role is not registered: {base_role}")
        if _role_key(base_role) != str(execution.get("base_role_key") or ""):
            raise ValueError(f"professional model/base role mismatch: {role_id}")
        execution_kind = str(execution.get("execution_kind") or "")
        execution_tier = str(execution.get("execution_tier") or "")
        if execution_kind not in {"cli_agent", "deterministic_tool"}:
            raise ValueError(f"professional execution kind is invalid: {role_id}")
        if not execution_tier:
            raise ValueError(f"professional execution tier is missing: {role_id}")
        resolved[role_id] = {
            **deepcopy(dict(profile)),
            "runtime": {
                "model_profile_ref": model_ref,
                "base_role_key": execution["base_role_key"],
                "execution_tier": execution_tier,
                "execution_kind": execution_kind,
                "deterministic": execution_kind == "deterministic_tool",
            },
        }
    contract = {
        "schema_version": "narrative-author-team/v2",
        "contract_id": composition.get("contract_id"),
        "description": composition.get("description"),
        "roles": resolved,
        "activation": {
            "base_chapter_roles": composition.get("base_chapter_roles"),
            "full_team_risks": composition.get("full_team_risks"),
            "risk_role_map": composition.get("risk_role_map"),
        },
        "authority_bindings": {
            "composition": {
                "path": selected.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(selected.read_bytes()).hexdigest(),
            },
            "role_manifests": {
                "path": registry_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(registry_path.read_bytes()).hexdigest(),
            },
            "model_profiles": {
                "path": model_path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
            },
        },
    }
    validation = validate_author_team_contract(contract)
    if validation["status"] != "pass":
        raise ValueError(
            "resolved author-team contract is invalid: "
            + ",".join(validation["issues"])
        )
    return contract


def validate_author_team_contract(
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate the full v2 team contract and its separation-of-duty gates."""

    issues: list[str] = []
    if contract.get("schema_version") != "narrative-author-team/v2":
        issues.append("schema_version_must_be_narrative_author_team_v2")
    roles = contract.get("roles")
    if not isinstance(roles, Mapping):
        roles = {}
        issues.append("roles_mapping_required")
    role_ids = {str(role_id) for role_id in roles}
    for role_id in REQUIRED_AUTHOR_ROLES:
        if role_id not in roles:
            issues.append(f"missing_required_role:{role_id}")
    for role_id in sorted(role_ids - set(REQUIRED_AUTHOR_ROLES)):
        issues.append(f"unknown_role:{role_id}")
    for role_id in REQUIRED_AUTHOR_ROLES:
        raw = roles.get(role_id)
        if not isinstance(raw, Mapping):
            continue
        for field in _REQUIRED_FIELDS:
            if field not in raw:
                issues.append(f"{role_id}:{field}_required")
        if raw.get("manifest_version") != 2:
            issues.append(f"{role_id}:manifest_version_must_be_2")
        for field in (
            "professional_duties",
            "knowledge_namespaces",
            "forbidden_actions",
            "acceptance_rules",
        ):
            if field in raw and not _nonempty_strings(raw.get(field)):
                issues.append(f"{role_id}:{field}_must_be_nonempty_strings")
        for field in ("tools", "dependencies"):
            if field in raw and (
                not isinstance(raw.get(field), list)
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in raw.get(field, [])
                )
            ):
                issues.append(f"{role_id}:{field}_must_be_strings")
        dependencies = raw.get("dependencies")
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if (
                    isinstance(dependency, str)
                    and dependency not in role_ids
                ):
                    issues.append(
                        f"{role_id}:unknown_dependency:{dependency}"
                    )
        for field in ("input_schema", "output_schema"):
            if field in raw and (
                not isinstance(raw.get(field), str)
                or not str(raw.get(field)).strip()
            ):
                issues.append(f"{role_id}:{field}_required")
        runtime = raw.get("runtime")
        if not isinstance(runtime, Mapping):
            issues.append(f"{role_id}:runtime_mapping_required")
        else:
            for field in (
                "model_profile_ref",
                "base_role_key",
                "execution_tier",
                "execution_kind",
            ):
                if not str(runtime.get(field) or "").strip():
                    issues.append(f"{role_id}:runtime_{field}_required")
        authority = raw.get("authority")
        if not isinstance(authority, Mapping):
            issues.append(f"{role_id}:authority_mapping_required")
        else:
            for scope in ("read", "write"):
                values = authority.get(scope)
                if not isinstance(values, list) or any(
                    not isinstance(item, str) or not item.strip()
                    for item in values
                ):
                    issues.append(
                        f"{role_id}:authority_{scope}_must_be_strings"
                    )
    writer = roles.get("writer") if isinstance(roles, Mapping) else {}
    writer = writer if isinstance(writer, Mapping) else {}
    writer_forbidden = set(writer.get("forbidden_actions") or [])
    for action, issue in (
        ("self_review", "writer:self_review_must_be_forbidden"),
        ("approve_own_work", "writer:approve_own_work_must_be_forbidden"),
        (
            "commit_narrative_state",
            "writer:commit_narrative_state_must_be_forbidden",
        ),
    ):
        if action not in writer_forbidden:
            issues.append(issue)
    writer_authority = writer.get("authority")
    writer_writes = (
        writer_authority.get("write") or []
        if isinstance(writer_authority, Mapping)
        else []
    )
    if any(
        str(scope).startswith(("project_brain/", "production/state"))
        for scope in writer_writes
    ):
        issues.append("writer:project_state_write_forbidden")
    projector = (
        roles.get("state_projector") if isinstance(roles, Mapping) else {}
    )
    projector = projector if isinstance(projector, Mapping) else {}
    projector_runtime = projector.get("runtime")
    projector_runtime = (
        projector_runtime
        if isinstance(projector_runtime, Mapping)
        else {}
    )
    if projector_runtime.get("deterministic") is not True:
        issues.append("state_projector:deterministic_runtime_required")
    if projector_runtime.get("execution_kind") != "deterministic_tool":
        issues.append("state_projector:generative_model_forbidden")

    dependency_graph = {
        role_id: tuple(
            str(item)
            for item in (
                roles.get(role_id, {}).get("dependencies", [])
                if isinstance(roles.get(role_id), Mapping)
                else []
            )
            if isinstance(item, str) and item in role_ids
        )
        for role_id in role_ids
    }
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(role_id: str) -> None:
        if role_id in visited:
            return
        if role_id in visiting:
            issues.append(f"dependency_cycle:{role_id}")
            return
        visiting.add(role_id)
        for dependency in dependency_graph.get(role_id, ()):
            visit(dependency)
        visiting.remove(role_id)
        visited.add(role_id)

    for role_id in sorted(role_ids):
        visit(role_id)
    dag_status = (
        "pass"
        if not any(
            issue.startswith(("dependency_cycle:",))
            or ":unknown_dependency:" in issue
            for issue in issues
        )
        else "blocked"
    )
    return {
        "schema_version": "narrative-author-team-validation/v1",
        "status": "pass" if not issues else "blocked",
        "contract_id": contract.get("contract_id"),
        "role_count": len(role_ids),
        "roles": sorted(role_ids),
        "writer_boundary": {
            "self_review_forbidden": "self_review" in writer_forbidden,
            "approval_forbidden": "approve_own_work" in writer_forbidden,
            "state_commit_forbidden": (
                "commit_narrative_state" in writer_forbidden
            ),
        },
        "state_projector": {
            "deterministic": projector_runtime.get("deterministic") is True,
            "execution_kind": projector_runtime.get("execution_kind"),
            "model_profile_ref": projector_runtime.get("model_profile_ref"),
        },
        "dependency_dag": {
            "status": dag_status,
            "node_count": len(dependency_graph),
        },
        "issues": sorted(set(issues)),
    }


def select_author_team(
    contract: Mapping[str, Any],
    *,
    risk_flags: Sequence[str],
) -> dict[str, Any]:
    """Select the smallest validated role subgraph for one chapter."""

    validation = validate_author_team_contract(contract)
    if validation["status"] != "pass":
        return {
            "schema_version": "narrative-author-team-selection/v1",
            "status": "blocked",
            "active_roles": [],
            "inactive_roles": [],
            "full_team": False,
            "issues": ["invalid_author_team_contract", *validation["issues"]],
        }
    activation = contract.get("activation")
    activation = activation if isinstance(activation, Mapping) else {}
    base_roles = activation.get("base_chapter_roles")
    full_team_risks = activation.get("full_team_risks")
    risk_role_map = activation.get("risk_role_map")
    if (
        not isinstance(base_roles, list)
        or not isinstance(full_team_risks, list)
        or not isinstance(risk_role_map, Mapping)
    ):
        return {
            "schema_version": "narrative-author-team-selection/v1",
            "status": "blocked",
            "active_roles": [],
            "inactive_roles": list(REQUIRED_AUTHOR_ROLES),
            "full_team": False,
            "issues": ["invalid_activation_policy"],
        }
    known_risks = set(full_team_risks) | set(risk_role_map)
    normalized = [str(flag).strip() for flag in risk_flags]
    unknown = sorted(set(normalized) - known_risks)
    if unknown:
        return {
            "schema_version": "narrative-author-team-selection/v1",
            "status": "blocked",
            "active_roles": [],
            "inactive_roles": list(REQUIRED_AUTHOR_ROLES),
            "full_team": False,
            "issues": [f"unknown_risk_flag:{flag}" for flag in unknown],
        }
    full_team = bool(set(normalized) & set(full_team_risks))
    active = (
        set(REQUIRED_AUTHOR_ROLES)
        if full_team else set(base_roles)
    )
    if not full_team:
        for flag in normalized:
            active.update(risk_role_map.get(flag, ()))
    active_roles = [
        role_id for role_id in REQUIRED_AUTHOR_ROLES if role_id in active
    ]
    inactive_roles = [
        role_id for role_id in REQUIRED_AUTHOR_ROLES if role_id not in active
    ]
    return {
        "schema_version": "narrative-author-team-selection/v1",
        "status": "pass",
        "contract_id": contract.get("contract_id"),
        "risk_flags": normalized,
        "active_roles": active_roles,
        "inactive_roles": inactive_roles,
        "full_team": full_team,
        "issues": [],
    }


def build_author_team_manifests(
    contract: Mapping[str, Any],
) -> tuple[AgentManifest, ...]:
    """Compile effective professional profiles into Project Agent manifests."""

    validation = validate_author_team_contract(contract)
    if validation["status"] != "pass":
        raise ValueError(
            "author-team contract is invalid: "
            + ",".join(validation["issues"])
        )
    roles = contract["roles"]
    project_id = str(contract.get("project_id") or "template")
    manifests: list[AgentManifest] = []
    for role_id in REQUIRED_AUTHOR_ROLES:
        profile = roles[role_id]
        runtime = profile["runtime"]
        authority = profile["authority"]
        manifests.append(
            AgentManifest(
                id=role_id,
                name=role_id.replace("_", " ").title(),
                version="2.0.0",
                role=role_id,
                description="; ".join(profile["professional_duties"]),
                responsibilities=tuple(profile["professional_duties"]),
                runtime_role=str(profile["extends_agent_role"]),
                read_scope=tuple(authority["read"]),
                write_scope=tuple(authority["write"]),
                approval_scope=(
                    ("authorial_decision",)
                    if role_id == "authorial_director"
                    else ()
                ),
                knowledge_binding={
                    "isolation": "project_private",
                    "namespace": f"agent.{project_id}.{role_id}",
                    "namespaces": list(profile["knowledge_namespaces"]),
                    "input_schema": profile["input_schema"],
                    "output_schema": profile["output_schema"],
                },
                model_profile=str(runtime["model_profile_ref"]),
                tool_permission=tuple(profile["tools"]),
                budget_profile=str(runtime["execution_tier"]),
                status="active",
                acceptance_rules=tuple(profile["acceptance_rules"]),
                collaboration={
                    "dependencies": list(profile["dependencies"]),
                    "forbidden_actions": list(profile["forbidden_actions"]),
                },
            )
        )
    return tuple(manifests)


def _proposal_sha256(value: Mapping[str, Any]) -> str:
    payload = {
        key: item
        for key, item in value.items()
        if key != "proposal_sha256"
    }
    return hashlib.sha256(
        yaml.safe_dump(
            payload,
            sort_keys=True,
            allow_unicode=True,
        ).encode("utf-8")
    ).hexdigest()


def _manifest_contract_identity(manifest: AgentManifest) -> dict[str, Any]:
    document = manifest.to_dict()
    identity = document.get("identity")
    if isinstance(identity, dict):
        identity.pop("manifest_revision", None)
    document.pop("lifecycle", None)
    return document


def materialize_author_team_contract(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    template_path: Path | None = None,
) -> dict[str, Any]:
    """Create a hash-bound run-local registration proposal."""

    if not _PROJECT_ID.fullmatch(project):
        raise ValueError("project identifier is invalid")
    if not _TASK_ID.fullmatch(task_id):
        raise ValueError("task identifier is invalid")
    root = Path(agentlab_root).resolve()
    source = (
        Path(template_path)
        if template_path is not None
        else root / "config" / "narrative_author_team.yml"
    ).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise ValueError("author-team template must be inside AgentLab root") from exc
    source_bytes = source.read_bytes()
    contract = load_author_team_contract(
        root,
        composition_path=source,
    )
    contract["project_id"] = project
    contract["contract_id"] = f"{project}-professional-author-team"
    contract["template_binding"] = {
        "path": source.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
    }
    validation = validate_author_team_contract(contract)
    if validation["status"] != "pass":
        raise ValueError(
            "author-team template is invalid: " + ",".join(validation["issues"])
        )
    manifests = build_author_team_manifests(contract)
    proposal = {
        "schema_version": "narrative-author-team-registration-proposal/v1",
        "status": "proposed",
        "candidate_only": True,
        "production_modified": False,
        "project_id": project,
        "task_id": task_id,
        "contract": contract,
        "manifests": [manifest.to_dict() for manifest in manifests],
    }
    proposal["proposal_sha256"] = _proposal_sha256(proposal)
    target = (
        root
        / "projects"
        / project
        / "runs"
        / task_id
        / "artifacts"
        / "author_team_registration_proposal.yml"
    )
    if target.is_file():
        current = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if current != proposal:
            raise ValueError(
                "author-team proposal already exists with different content"
            )
        status = "current"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_yaml(target, proposal)
        status = "proposed"
    return {
        "schema_version": "narrative-author-team-proposal-receipt/v1",
        "status": status,
        "project_id": project,
        "task_id": task_id,
        "proposal_path": target.relative_to(root).as_posix(),
        "proposal_sha256": proposal["proposal_sha256"],
        "template_sha256": contract["template_binding"]["sha256"],
        "role_count": len(REQUIRED_AUTHOR_ROLES),
        "production_modified": False,
    }


@contextmanager
def _author_team_provision_lock(project_root: Path) -> Iterator[None]:
    lock_root = project_root / ".project_truth"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / ".author-team-provision.lock"
    if lock_path.is_symlink():
        raise ValueError("author-team provision lock may not be a symlink")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def register_author_team_proposal(
    agentlab_root: Path,
    *,
    project: str,
    proposal_path: Path,
    expected_proposal_sha256: str,
    expected_snapshot_id: str,
    actor_id: str,
    approved: bool,
) -> dict[str, Any]:
    """Serialize KnowledgeStore provisioning with the Project Truth commit."""

    if not _PROJECT_ID.fullmatch(project):
        raise ValueError("project identifier is invalid")
    root = Path(agentlab_root).resolve()
    project_root = root / "projects" / project
    if project_root.is_symlink() or not project_root.is_dir():
        raise ValueError("project root is invalid")
    with _author_team_provision_lock(project_root.resolve()):
        return _register_author_team_proposal_unlocked(
            root,
            project=project,
            proposal_path=proposal_path,
            expected_proposal_sha256=expected_proposal_sha256,
            expected_snapshot_id=expected_snapshot_id,
            actor_id=actor_id,
            approved=approved,
        )


def _register_author_team_proposal_unlocked(
    agentlab_root: Path,
    *,
    project: str,
    proposal_path: Path,
    expected_proposal_sha256: str,
    expected_snapshot_id: str,
    actor_id: str,
    approved: bool,
) -> dict[str, Any]:
    """Atomically register an approved team proposal into Project Truth."""

    if not approved:
        raise ValueError("author-team registration requires explicit approval")
    root = Path(agentlab_root).resolve()
    project_root = (root / "projects" / project).resolve()
    selected = Path(proposal_path).resolve()
    try:
        selected.relative_to(project_root / "runs")
    except ValueError as exc:
        raise ValueError("author-team proposal must be run-local") from exc
    proposal = _read_yaml_mapping(selected, label="author-team proposal")
    if (
        proposal.get("schema_version")
        != "narrative-author-team-registration-proposal/v1"
        or proposal.get("project_id") != project
        or proposal.get("candidate_only") is not True
        or proposal.get("production_modified") is not False
    ):
        raise ValueError("author-team proposal contract is invalid")
    actual_sha256 = _proposal_sha256(proposal)
    if (
        proposal.get("proposal_sha256") != actual_sha256
        or expected_proposal_sha256 != actual_sha256
    ):
        raise ValueError("author-team proposal hash mismatch")
    contract = proposal.get("contract")
    if not isinstance(contract, Mapping):
        raise ValueError("author-team proposal has no contract")
    manifests = build_author_team_manifests(contract)
    if proposal.get("manifests") != [
        manifest.to_dict() for manifest in manifests
    ]:
        raise ValueError("author-team proposal manifest snapshot mismatch")
    namespaces = [
        str(manifest.knowledge_binding.get("namespace") or "")
        for manifest in manifests
    ]
    expected_namespaces = [
        f"agent.{project}.{role_id}" for role_id in REQUIRED_AUTHOR_ROLES
    ]
    if namespaces != expected_namespaces or len(set(namespaces)) != len(
        manifests
    ):
        raise ValueError("author-team private knowledge namespaces are invalid")
    validation = validate_author_team_contract(contract)
    if validation["dependency_dag"]["status"] != "pass":
        raise ValueError("author-team dependency DAG is invalid")
    knowledge_store = KnowledgeStore(root)
    preexisting_namespaces = {
        namespace
        for namespace in namespaces
        if knowledge_store.space_exists(namespace)
    }
    truth = ProjectTruthStore(project_root)
    pre_registration_audit = truth.audit()
    if pre_registration_audit.get("status") != "pass":
        raise ValueError("project truth pre-registration audit did not pass")
    knowledge_paths = []
    try:
        for namespace in namespaces:
            knowledge_paths.append(knowledge_store.ensure_space(namespace))
    except BaseException:
        knowledge_store.retire_spaces(
            namespace
            for namespace in namespaces
            if namespace not in preexisting_namespaces
            and knowledge_store.space_exists(namespace)
        )
        raise
    registry = ProjectAgentRegistry(truth)
    current_manifests: list[AgentManifest] = []
    for manifest in manifests:
        try:
            current_manifests.append(registry.get(manifest.id))
        except AgentContractViolation:
            continue
    try:
        if current_manifests:
            if len(current_manifests) != len(manifests):
                raise ValueError(
                    "author-team registration found a partial existing team"
                )
            statuses = {
                current_manifest.status
                for current_manifest in current_manifests
            }
            for current_manifest, proposed_manifest in zip(
                current_manifests,
                manifests,
            ):
                if (
                    _manifest_contract_identity(current_manifest)
                    != _manifest_contract_identity(proposed_manifest)
                ):
                    raise ValueError(
                        "existing author team is not a matching compensated team"
                    )
            if statuses == {"archived"}:
                current_snapshot_id = truth.current().snapshot_id
                receipt = truth.commit(
                    ChangeSet(
                        project_id=truth.current().project_id,
                        expected_snapshot_id=current_snapshot_id,
                        actor_id=actor_id,
                        idempotency_key=(
                            f"author-team-reactivate:{actual_sha256}:"
                            f"{current_snapshot_id}"
                        ),
                        reason=(
                            "Reactivate an unchanged author team after a "
                            "compensated post-registration audit failure."
                        ),
                        resources=tuple(
                            ResourceChange(
                                key=f"agents.manifest.{current_manifest.id}",
                                content=current_manifest.evolve(
                                    status="active"
                                ).to_dict(),
                            )
                            for current_manifest in current_manifests
                        ),
                    )
                )
                registration_mode = "reactivated_compensated_team"
                receipt_document = receipt.to_dict()
            elif statuses == {"active"}:
                current_snapshot_id = truth.current().snapshot_id
                registration_mode = "existing_active_team"
                receipt_document = {
                    "schema_version": (
                        "narrative-author-team-existing-registration/v1"
                    ),
                    "project_id": project,
                    "snapshot_id": current_snapshot_id,
                    "original_expected_snapshot_id": expected_snapshot_id,
                    "proposal_sha256": actual_sha256,
                    "status": "current",
                }
            else:
                raise ValueError(
                    "existing author team has mixed lifecycle states"
                )
        else:
            receipt = registry.register_many(
                manifests,
                expected_snapshot_id=expected_snapshot_id,
                actor_id=actor_id,
                source="user",
                approved=True,
            )
            registration_mode = "new_team"
            receipt_document = receipt.to_dict()
    except BaseException:
        knowledge_store.retire_spaces(
            namespace
            for namespace in namespaces
            if namespace not in preexisting_namespaces
        )
        raise
    try:
        truth_audit = truth.audit()
        if truth_audit.get("status") != "pass":
            raise ValueError("project truth post-registration audit did not pass")
    except BaseException as audit_error:
        compensation_succeeded = False
        try:
            current = truth.current()
            truth.commit(
                ChangeSet(
                    project_id=current.project_id,
                    expected_snapshot_id=current.snapshot_id,
                    actor_id=actor_id,
                    idempotency_key=(
                        f"author-team-audit-compensation:{actual_sha256}:"
                        f"{current.snapshot_id}"
                    ),
                    reason=(
                        "Archive author team because its post-registration "
                        "Project Truth audit failed."
                    ),
                    resources=tuple(
                        ResourceChange(
                            key=f"agents.manifest.{manifest.id}",
                            content=registry.get(manifest.id)
                            .evolve(status="archived")
                            .to_dict(),
                        )
                        for manifest in manifests
                    ),
                ),
            )
            compensation_succeeded = True
        finally:
            if compensation_succeeded:
                knowledge_store.retire_spaces(
                    namespace
                    for namespace in namespaces
                    if namespace not in preexisting_namespaces
                )
        raise ValueError(
            "author-team registration compensated after failed truth audit"
        ) from audit_error
    return {
        "schema_version": "narrative-author-team-registration-receipt/v1",
        "status": "registered",
        "project_id": project,
        "proposal_sha256": actual_sha256,
        "atomic_registration": True,
        "registration_mode": registration_mode,
        "registered_roles": list(REQUIRED_AUTHOR_ROLES),
        "knowledge_spaces": [
            {
                "role_id": role_id,
                "namespace": namespace,
                "path": path.relative_to(root).as_posix(),
            }
            for role_id, namespace, path in zip(
                REQUIRED_AUTHOR_ROLES,
                namespaces,
                knowledge_paths,
            )
        ],
        "dependency_dag_audit": validation["dependency_dag"],
        "project_truth_audit": truth_audit,
        "pre_registration_truth_audit": pre_registration_audit,
        "canonical_receipt": receipt_document,
    }
