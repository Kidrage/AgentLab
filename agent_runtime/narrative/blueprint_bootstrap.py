"""Create a governed blueprint task before a narrative project has canon."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

import yaml

from agent_runtime.atomic_io import atomic_write_json, atomic_write_text, atomic_write_yaml
from agent_runtime.production_protocols import (
    ProductionProtocolRunner,
    compile_production_protocol,
)
from agent_runtime.project_truth import (
    ChangeSet,
    ProjectTruthStore,
    ResourceChange,
)
from agent_runtime.task_runtime_v2 import TaskRuntime
from agent_runtime.task_runtime_v2.role_executor import RoleAttemptExecutor


_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ALLOWED_EXPLICITNESS = {"none", "suggestive", "non_graphic"}
_GOVERNANCE_ONLY_PRODUCTION_FILES = frozenset({"outbound_context_policy.yml"})


def _nonempty(value: object, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"blueprint request {field} is required")
    return text


def _has_story_production(production: Path) -> bool:
    """Distinguish story production from task-scoped governance files."""

    if not production.exists():
        return False
    if production.is_symlink() or not production.is_dir():
        return True
    for child in production.iterdir():
        if (
            child.name in _GOVERNANCE_ONLY_PRODUCTION_FILES
            and child.is_file()
            and not child.is_symlink()
        ):
            continue
        return True
    return False


def _load_request(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read blueprint request: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("blueprint request must be a mapping")
    return value


def _validate_request(request: Mapping[str, Any], *, project: str) -> None:
    if request.get("schema_version") != "narrative-blueprint-request/v1":
        raise ValueError(
            "blueprint request schema_version must be narrative-blueprint-request/v1"
        )
    if request.get("project") != project:
        raise ValueError("blueprint request project mismatch")
    _nonempty(request.get("title"), field="title")
    genres = request.get("genres")
    if not isinstance(genres, list) or not genres or any(
        not isinstance(item, str) or not item.strip() for item in genres
    ):
        raise ValueError("blueprint request genres must be a non-empty string list")
    chapters = request.get("target_total_chapters")
    characters = request.get("target_han_characters")
    if isinstance(chapters, bool) or not isinstance(chapters, int) or chapters < 1:
        raise ValueError("blueprint request target_total_chapters must be positive")
    if (
        isinstance(characters, bool)
        or not isinstance(characters, int)
        or characters < chapters
    ):
        raise ValueError(
            "blueprint request target_han_characters must cover every chapter"
        )
    seed = request.get("creative_seed")
    if not isinstance(seed, Mapping):
        raise ValueError("blueprint request creative_seed must be a mapping")
    _nonempty(seed.get("premise"), field="creative_seed.premise")
    _nonempty(seed.get("ending"), field="creative_seed.ending")
    boundary = request.get("content_boundary")
    if not isinstance(boundary, Mapping):
        raise ValueError("blueprint request content_boundary must be a mapping")
    for field in (
        "all_romance_participants_adults",
        "contextual_consent",
        "exit_right",
    ):
        if boundary.get(field) is not True:
            raise ValueError(f"blueprint request content_boundary.{field} is required")
    if boundary.get("explicitness") not in _ALLOWED_EXPLICITNESS:
        raise ValueError("blueprint request explicit content is forbidden")


def create_blueprint_task(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    request_path: Path,
) -> dict[str, Any]:
    """Bind one creative brief to the full professional blueprint protocol."""

    root = Path(agentlab_root).resolve()
    project = str(project or "").strip()
    if not _PROJECT_ID.fullmatch(project):
        raise ValueError("project must be a safe AgentLab identifier")
    source = Path(request_path).resolve(strict=True)
    if source == root or root not in source.parents:
        raise ValueError("blueprint request must be inside the AgentLab root")
    production = root / "projects" / project / "production"
    if _has_story_production(production):
        raise ValueError("new-project blueprint task cannot target existing production")

    request = _load_request(source)
    _validate_request(request, project=project)
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    source_relative = source.relative_to(root).as_posix()
    governed_source_relative = (
        Path("projects")
        / project
        / "runtime"
        / "tasks"
        / task_id
        / "inputs"
        / "creative-brief.yml"
    ).as_posix()
    profile = {
        "kind": "blueprint_build",
        "scope": "longform",
        "target_count": int(request["target_total_chapters"]),
        "canon_impact": "new_project",
        "risk_flags": list(request.get("risk_flags") or []),
        "project": project,
        "source_creative_brief": governed_source_relative,
        "source_creative_brief_sha256": source_sha256,
    }
    # Admission must be side-effect free: reject a brief before TaskRuntime
    # records the first immutable event, otherwise a compiler failure leaves a
    # misleading created Task that can never match a corrected source hash.
    compile_production_protocol(
        root,
        protocol_ref="narrative.blueprint.v1",
        task_facts=profile,
    )
    runtime = TaskRuntime(root, project=project)
    runtime.create_task(
        task_id=task_id,
        title=f"Generate blueprint: {_nonempty(request.get('title'), field='title')}",
        user_goal=(
            f"Create a governed {profile['target_count']}-chapter longform blueprint "
            f"for《{request['title']}》 "
            "without promoting candidate artifacts before human acceptance."
        ),
        protocol_ref="narrative.blueprint.v1",
        input_profile=profile,
        idempotency_key=f"blueprint-create-{source_sha256[:24]}",
    )
    governed_source = root / governed_source_relative
    atomic_write_text(governed_source, source.read_text(encoding="utf-8"))
    if hashlib.sha256(governed_source.read_bytes()).hexdigest() != source_sha256:
        raise RuntimeError("governed creative brief copy hash mismatch")
    projection = ProductionProtocolRunner(root, project=project).prepare(task_id)
    task_root = runtime._task_dir(task_id)
    input_root = task_root / "inputs"
    messages_path = input_root / "blueprint-role-messages.json"
    external_request_path = input_root / "external-context-request.yml"
    atomic_write_json(
        messages_path,
        [
            {
                "role": "user",
                "content": (
                    f"Execute the governed {profile['target_count']}-chapter "
                    f"blueprint work item for《{request['title']}》. Produce only "
                    "the candidate artifact assigned to this role, in Chinese, "
                    "with explicit identifiers, causality, costs, state changes, "
                    "and source-bound constraints. Preserve adult consent and exit "
                    "rights. Do not promote or rewrite project production."
                ),
            }
        ],
    )
    atomic_write_yaml(
        external_request_path,
        {
            "purpose": "Execute one bounded longform blueprint role.",
            "minimal_fragment": (
                "Use only the governed creative brief and predecessor candidate "
                "artifacts; external retrieval is not requested."
            ),
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=24)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
    )
    return {
        "schema_version": "narrative-blueprint-task/v1",
        "status": "prepared",
        "project": project,
        "task": projection["task"],
        "work_items": projection["work_items"],
        "source": {
            "path": source_relative,
            "sha256": source_sha256,
            "governed_copy_path": governed_source_relative,
        },
        "execution_inputs": {
            "messages_path": messages_path.relative_to(root).as_posix(),
            "external_context_request_path": external_request_path.relative_to(
                root
            ).as_posix(),
        },
        "production_modified": False,
    }


def authorize_blueprint_outbound(
    agentlab_root: Path,
    *,
    project: str,
    task_id: str,
    authorized_by: str,
) -> dict[str, Any]:
    """Record narrow user authority for one candidate-only blueprint Task."""

    root = Path(agentlab_root).resolve()
    runtime = TaskRuntime(root, project=project)
    projection = runtime.load_task(task_id)
    task = projection["task"]
    if task.get("protocol_ref") != "narrative.blueprint.v1":
        raise ValueError("outbound authority requires a narrative blueprint task")
    actor = _nonempty(authorized_by, field="authorized_by")
    executor = RoleAttemptExecutor(root, project=project)
    recipients: set[str] = set()
    roles: set[str] = set()
    for work_item in projection["work_items"].values():
        if work_item.get("execution_kind") != "cli_agent":
            continue
        role = str(work_item.get("protocol_role") or "")
        profile, provider, _model_profile = executor._resolve_bound_profile(
            role,
            work_item,
        )
        roles.add(role)
        recipients.add(
            f"cli_agent:{str(profile.get('cli_agent') or '').strip()};"
            f"runtime_provider:{provider}"
        )
    if not recipients or not roles:
        raise ValueError("blueprint task has no resolvable outbound roles")

    external_request_path = (
        runtime._task_dir(task_id) / "inputs" / "external-context-request.yml"
    )
    try:
        external_request = yaml.safe_load(
            external_request_path.read_text(encoding="utf-8")
        ) or {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("blueprint external context request is invalid") from exc
    if not isinstance(external_request, dict):
        raise ValueError("blueprint external context request must be a mapping")
    project_root = root / "projects" / project
    policy_path = project_root / "production" / "outbound_context_policy.yml"
    truth = ProjectTruthStore(project_root)
    truth.initialize(project)
    current = truth.current()
    existing = current.resources.get("policies.outbound_context_auto_approval")
    authorized_at = datetime.now(timezone.utc).isoformat()
    if (
        existing is not None
        and isinstance(existing.content, dict)
        and existing.content.get("task_id") == task_id
        and existing.content.get("authorized_by") == actor
        and policy_path.is_file()
        and not policy_path.is_symlink()
        and hashlib.sha256(policy_path.read_bytes()).hexdigest()
        == existing.content.get("policy_sha256")
    ):
        try:
            existing_policy = yaml.safe_load(
                policy_path.read_text(encoding="utf-8")
            ) or {}
        except (OSError, UnicodeError, yaml.YAMLError):
            existing_policy = {}
        prior_authorized_at = (
            (existing_policy.get("authorization") or {}).get("authorized_at")
            if isinstance(existing_policy, dict)
            else None
        )
        if str(prior_authorized_at or "").strip():
            authorized_at = str(prior_authorized_at)
    policy = {
        "schema_version": "narrative-outbound-auto-approval/v1",
        "status": "active",
        "project": project,
        "authorization": {
            "mode": "policy_auto_approve",
            "user_authorized": True,
            "user_authorized_by": actor,
            "authorized_at": authorized_at,
            "user_responsibility": "candidate_acceptance_only",
            "statement": (
                "Authorize bounded external execution for this exact blueprint "
                "task; story candidates and state projection still require "
                "explicit user acceptance."
            ),
        },
        "constraints": {
            "allowed_recipients": sorted(recipients),
            "allowed_roles": sorted(roles),
            "allowed_task_ids": [task_id],
            "allowed_source_roots": ["runtime"],
            "max_source_files": 32,
            "max_total_bytes": 2_097_152,
            "max_expiry_hours": 48,
            "candidate_only": True,
            "state_projection_requires_user_acceptance": True,
            "fallback_allowed": False,
        },
    }
    policy_bytes = yaml.safe_dump(
        policy,
        sort_keys=False,
        allow_unicode=True,
    ).encode("utf-8")
    policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
    authority = {
        "schema_version": "narrative-outbound-auto-approval-authority/v1",
        "status": "active",
        "project": project,
        "task_id": task_id,
        "policy_path": "production/outbound_context_policy.yml",
        "policy_sha256": policy_sha256,
        "authorized_by": actor,
    }
    if existing is None or existing.content != authority:
        receipt = truth.commit(
            ChangeSet(
                project_id=project,
                expected_snapshot_id=current.snapshot_id,
                actor_id=actor,
                idempotency_key=(
                    f"authorize-blueprint-outbound-{task_id}-{policy_sha256[:16]}"
                ),
                reason="User-authorized candidate-only blueprint execution.",
                resources=(
                    ResourceChange(
                        key="policies.outbound_context_auto_approval",
                        content=authority,
                    ),
                ),
            )
        )
        current = truth.current()
        snapshot_id = receipt.snapshot_id
    else:
        snapshot_id = current.snapshot_id
    revision = current.resources["policies.outbound_context_auto_approval"]
    # Project Truth is the authority. Materialize the policy only after its
    # immutable revision commits, so a failed commit cannot leave production
    # policy ahead of the truth snapshot. Replays write identical bytes.
    atomic_write_yaml(policy_path, policy)
    if hashlib.sha256(policy_path.read_bytes()).hexdigest() != policy_sha256:
        raise RuntimeError("outbound context policy materialization drifted")
    return {
        "schema_version": "narrative-blueprint-outbound-authorization/v1",
        "status": "active",
        "project": project,
        "task_id": task_id,
        "authorized_by": actor,
        "policy_path": policy_path.relative_to(root).as_posix(),
        "policy_sha256": policy_sha256,
        "truth_snapshot_id": snapshot_id,
        "truth_revision_id": revision.revision_id,
        "candidate_only": True,
        "state_projection_requires_user_acceptance": True,
    }
