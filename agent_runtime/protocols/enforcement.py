"""Protocol packet generation and enforcement checks.

The module intentionally keeps the protocol deterministic. It reads local
AgentLab artifacts and policy YAML files, then produces bounded packets that
frontdesk and worker CLI agents can consume without rediscovering the whole
repository.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import subprocess
from typing import Any

import yaml


AGENTLAB_ROLES = [
    "Supervisor",
    "RepoScout",
    "Researcher",
    "InterfaceMapper",
    "PromptEngineer",
    "Coder",
    "ArtifactProducer",
    "TesterAuditor",
    "Verifier",
    "Archivist",
]


@dataclass
class ProtocolCheck:
    id: str
    status: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _read_yaml(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or default
    except Exception:
        return default


def _safe_text(path: Path, max_chars: int = 4000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
        return text[:max_chars]
    except Exception:
        return ""


def _git_value(root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _load_policy(root: Path, name: str) -> dict[str, Any]:
    return _read_yaml(root / "config" / name, {}) or {}


def _normalize_role(role: str) -> str:
    text = str(role or "").replace("_", "").replace("-", "").lower()
    for canonical in AGENTLAB_ROLES:
        if canonical.replace("_", "").replace("-", "").lower() == text:
            return canonical
    return str(role or "")


def _task_state(root: Path, project: str, task_id: str | None = None) -> dict[str, Any]:
    project_dir = root / "projects" / project
    runs_dir = project_dir / "runs"
    selected: Path | None = None
    if task_id:
        candidate = runs_dir / task_id
        if candidate.is_dir():
            selected = candidate
    elif runs_dir.is_dir():
        task_dirs = [p for p in runs_dir.iterdir() if p.is_dir() and p.name.startswith("task_")]
        if task_dirs:
            selected = max(task_dirs, key=lambda p: p.stat().st_mtime)

    if not selected:
        return {
            "project": project,
            "task_id": task_id or "",
            "known": False,
            "status": "unknown",
            "source_files": [],
        }

    state = _read_yaml(selected / "state.yml", {}) or {}
    task_card = _read_yaml(selected / "task_card.yml", {}) or {}
    lifecycle = _read_yaml(selected / "lifecycle.yml", {}) or {}
    artifact_manifest = _read_yaml(selected / "artifact_manifest.yml", {}) or {}
    sources = [
        str(path.relative_to(root))
        for path in [
            selected / "state.yml",
            selected / "task_card.yml",
            selected / "lifecycle.yml",
            selected / "artifact_manifest.yml",
        ]
        if path.exists()
    ]
    return {
        "project": project,
        "task_id": selected.name,
        "known": True,
        "status": state.get("status") or task_card.get("status") or "unknown",
        "last_event": state.get("last_event", ""),
        "updated_at": state.get("updated_at", ""),
        "artifact_pass_rate": (task_card.get("artifact_check") or {}).get("pass_rate")
        or artifact_manifest.get("pass_rate"),
        "lifecycle_next_node": lifecycle.get("next_node", ""),
        "source_files": sources,
    }


def _project_names(root: Path) -> list[str]:
    projects_dir = root / "projects"
    if not projects_dir.is_dir():
        return []
    return sorted([p.name for p in projects_dir.iterdir() if p.is_dir()])


def check_role_binding(root: Path, worker: str, role: str) -> tuple[bool, str]:
    bindings = _load_policy(root, "agent_role_bindings.yml")
    canonical_role = _normalize_role(role)
    worker_cfg = ((bindings.get("workers") or {}).get(worker) or {})
    role_cfg = ((bindings.get("roles") or {}).get(canonical_role) or {})
    allowed_by_worker = worker_cfg.get("allowed_roles") or []
    forbidden_by_worker = worker_cfg.get("forbidden_roles") or []
    allowed_by_role = role_cfg.get("allowed_workers") or []

    if not worker_cfg:
        return False, f"worker '{worker}' is not bound in config/agent_role_bindings.yml"
    if worker_cfg.get("frontdesk_capable") and not worker_cfg.get("worker_capable"):
        return False, f"worker '{worker}' is frontdesk-only and cannot execute AgentLab role '{canonical_role}'"
    if canonical_role in forbidden_by_worker:
        return False, f"worker '{worker}' is explicitly forbidden for role '{canonical_role}'"
    if canonical_role not in allowed_by_worker:
        return False, f"worker '{worker}' is not listed in allowed_roles for '{canonical_role}'"
    if worker not in allowed_by_role:
        return False, f"role '{canonical_role}' does not list worker '{worker}' in allowed_workers"
    return True, "role binding allowed"


def build_workspace_entry(
    root: Path,
    agent_id: str,
    *,
    project: str = "AgentLab",
    task_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    bindings = _load_policy(root, "agent_role_bindings.yml")
    workspace_policy = _load_policy(root, "workspace_entry_policy.yml")
    frontdesk_policy = _load_policy(root, "frontdesk_policy.yml")
    worker_cfg = ((bindings.get("workers") or {}).get(agent_id) or {})
    task = _task_state(root, project, task_id)
    branch = _git_value(root, ["branch", "--show-current"])
    head = _git_value(root, ["rev-parse", "HEAD"])

    return {
        "packet_type": "agentlab_workspace_entry",
        "schema_version": 1,
        "authority": workspace_policy.get("authority", "_shared/AGENT_PROTOCOL.md"),
        "workspace_root": str(root),
        "git": {
            "branch": branch or "HEAD",
            "head": head,
            "detached": not bool(branch),
        },
        "agent_id": agent_id,
        "allowed_profiles": {
            "frontdesk_capable": bool(worker_cfg.get("frontdesk_capable")),
            "worker_capable": bool(worker_cfg.get("worker_capable")),
            "allowed_roles": worker_cfg.get("allowed_roles") or [],
            "frontdesk_profiles": worker_cfg.get("frontdesk_profiles") or [],
        },
        "known_projects": _project_names(root),
        "recent_task_state": task,
        "required_next_step": "Use frontdesk-session for user-facing chat or role-session for assigned AgentLab work.",
        "forbidden_actions": list(dict.fromkeys([
            *(workspace_policy.get("forbidden_actions") or []),
            *(frontdesk_policy.get("forbidden_actions") or [] if worker_cfg.get("frontdesk_capable") else []),
        ])),
        "state_sources": task.get("source_files", []),
    }


def build_frontdesk_context(
    root: Path,
    agent_id: str,
    *,
    project: str = "AgentLab",
    task_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    frontdesk_policy = _load_policy(root, "frontdesk_policy.yml")
    bindings = _load_policy(root, "agent_role_bindings.yml")
    worker_cfg = ((bindings.get("workers") or {}).get(agent_id) or {})
    entry = build_workspace_entry(root, agent_id, project=project, task_id=task_id)
    return {
        "packet_type": "agentlab_frontdesk_context",
        "schema_version": 1,
        "agent_id": agent_id,
        "frontdesk_capable": bool(worker_cfg.get("frontdesk_capable")),
        "frontdesk_profile": (worker_cfg.get("frontdesk_profiles") or ["unbound"])[0],
        "role": "AgentLab Frontdesk / Chat Assistant Layer",
        "meaning": "Talk with the user, translate intent into AgentLab operations, and report grounded state.",
        "allowed_actions": frontdesk_policy.get("allowed_actions") or [],
        "forbidden_actions": frontdesk_policy.get("forbidden_actions") or [],
        "state_grounding": frontdesk_policy.get("state_grounding") or {},
        "workspace_entry": entry,
        "canonical_commands": {
            "status": "./agentlab.sh status --project <Project> --task-id <task_id>",
            "prepare": "./agentlab.sh prepare --project <Project> --task-id <task_id> --write-plan",
            "run_pipeline_dry": "./agentlab.sh run-pipeline --project <Project> --task-id <task_id> --dry-run",
            "frontdesk_doctor": f"./agentlab.sh frontdesk-doctor --agent {agent_id}",
            "role_session": "./agentlab.sh role-session --role <Role> --worker <worker> --project <Project> --task-id <task_id>",
        },
    }


def build_frontdesk_session(
    root: Path,
    agent_id: str,
    *,
    project: str = "AgentLab",
    task_id: str | None = None,
) -> str:
    context = build_frontdesk_context(root, agent_id, project=project, task_id=task_id)
    return "\n".join([
        "# AgentLab Frontdesk Session",
        "",
        "You are the AgentLab Frontdesk / Chat Assistant Layer.",
        "Use only this packet plus AgentLab CLI/artifacts for state. Do not rediscover the repository.",
        "Do not implement tasks or edit target files. Generate handoffs and invoke registered AgentLab contracts only.",
        "",
        "```yaml",
        yaml.safe_dump(context, sort_keys=False, allow_unicode=True).rstrip(),
        "```",
    ])


def build_role_session(
    root: Path,
    role: str,
    worker: str,
    *,
    project: str = "AgentLab",
    task_id: str = "task_0001",
) -> dict[str, Any]:
    root = Path(root)
    canonical_role = _normalize_role(role)
    allowed, reason = check_role_binding(root, worker, canonical_role)
    agent_registry = _load_policy(root, "agent_registry.yml")
    role_cfg = ((agent_registry.get("agents") or {}).get(canonical_role) or {})
    run_dir = root / "projects" / project / "runs" / task_id
    task = _task_state(root, project, task_id)
    packet = {
        "packet_type": "agentlab_role_session",
        "schema_version": 1,
        "authority": "_shared/AGENT_PROTOCOL.md",
        "role": canonical_role,
        "worker": worker,
        "binding": {
            "allowed": allowed,
            "reason": reason,
        },
        "project": project,
        "task_id": task_id,
        "task_state": task,
        "identity": role_cfg.get("role", f"AgentLab role {canonical_role}"),
        "must_read_artifacts": [
            str(path.relative_to(root))
            for path in [
                run_dir / "user_request.md",
                run_dir / "workflow_plan.yml",
                run_dir / "state.yml",
                run_dir / "task_card.yml",
            ]
            if path.exists()
        ],
        "required_outputs": role_cfg.get("required_outputs") or [],
        "source_write_policy": role_cfg.get("source_write_policy", "never_without_supervisor_plan"),
        "shell_policy": role_cfg.get("shell_policy", "inspect_only"),
        "forbidden_actions": [
            "ignore_role_binding",
            "work_outside_assigned_role",
            "edit_files_outside_supervisor_scope",
            "skip_validation_evidence",
            "silently_fallback_to_another_agent",
        ],
        "exit_report_must_include": [
            "role",
            "worker",
            "files_changed",
            "commands_run",
            "validation_results",
            "blockers",
            "artifact_paths",
        ],
    }
    if canonical_role == "ArtifactProducer":
        from agent_runtime.protocols.artifact_task import load_artifact_task_for_run

        artifact_task = load_artifact_task_for_run(root, project, task_id)
        packet["artifact_task"] = artifact_task or {
            "status": "missing",
            "required": True,
            "expected_path": str((run_dir / "artifact_task.yml").relative_to(root)),
            "message": "Supervisor must provide an ArtifactTask contract before ArtifactProducer executes.",
        }
        packet["forbidden_actions"].extend([
            "produce_non_code_artifact_without_artifact_task",
            "silently_change_output_format",
            "claim_generated_artifact_without_file_evidence",
        ])
        packet["exit_report_must_include"].extend([
            "produced_artifacts",
            "artifact_type",
            "provider_used",
            "fallback_status",
        ])
    return packet


def _check(status: bool, check_id: str, message: str, severity: str = "fail") -> ProtocolCheck:
    return ProtocolCheck(check_id, "pass" if status else "fail", severity, message)


def run_frontdesk_doctor(root: Path, agent_id: str) -> dict[str, Any]:
    root = Path(root)
    frontdesk = _load_policy(root, "frontdesk_policy.yml")
    bindings = _load_policy(root, "agent_role_bindings.yml")
    contracts = _load_policy(root, "worker_invocation_contracts.yml")
    worker_cfg = ((bindings.get("workers") or {}).get(agent_id) or {})
    contract = ((contracts.get("contracts") or {}).get(agent_id) or {})
    checks = [
        _check(bool(frontdesk), "frontdesk_policy_present", "frontdesk policy is present"),
        _check(bool(worker_cfg), "agent_binding_present", f"agent '{agent_id}' has a role binding"),
        _check(bool(worker_cfg.get("frontdesk_capable")), "frontdesk_capable", f"agent '{agent_id}' is frontdesk-capable"),
        _check(
            not (worker_cfg.get("frontdesk_capable") and not worker_cfg.get("worker_capable") and contract.get("invocation_style") == "task_packet_prompt"),
            "frontdesk_not_task_packet_worker",
            "frontdesk-only agents must not use task_packet_prompt invocation",
        ),
    ]
    return _doctor_result("frontdesk_doctor", checks)


def run_role_doctor(root: Path, role: str, worker: str) -> dict[str, Any]:
    allowed, reason = check_role_binding(Path(root), worker, role)
    packet = build_role_session(Path(root), role, worker, task_id="task_0001")
    checks = [
        _check(allowed, "role_binding_allowed", reason),
        _check(packet["packet_type"] == "agentlab_role_session", "role_session_generates", "role session packet generated"),
    ]
    return _doctor_result("role_doctor", checks, extra={"role_session": packet})


def run_protocol_doctor(root: Path) -> dict[str, Any]:
    root = Path(root)
    enforcement = _load_policy(root, "protocol_enforcement.yml")
    bindings = _load_policy(root, "agent_role_bindings.yml")
    contracts = _load_policy(root, "worker_invocation_contracts.yml")
    collaboration = _load_policy(root, "agent_collaboration.yml").get("agent_collaboration", {})
    shared_directory = _load_policy(root, "shared_agent_directory.yml")
    artifact_policy = _load_policy(root, "artifact_task_policy.yml")
    checks: list[ProtocolCheck] = []

    for rel in enforcement.get("required_protocol_docs") or []:
        checks.append(_check((root / rel).exists(), "required_doc_present", f"{rel} exists"))
    for rel in enforcement.get("required_configs") or []:
        checks.append(_check((root / rel).exists(), "required_config_present", f"{rel} exists"))

    peer = collaboration.get("peer_discovery") or {}
    checks.extend([
        _check(bool(peer.get("required_before_first_collaboration")), "peer_discovery_required", "peer discovery is required before first collaboration"),
        _check(bool(peer.get("require_target_command_validation")), "target_command_validation_required", "target command validation is required"),
        _check(bool(peer.get("require_status_and_lock_check")), "status_lock_check_required", "status and lock checks are required"),
    ])

    repo_handoff = collaboration.get("repository_handoff") or {}
    checks.extend([
        _check(bool(repo_handoff.get("required_for_all_agents")), "repository_handoff_required", "repository handoff is required for all agents"),
        _check(bool(repo_handoff.get("discover_before_repository_read")), "handoff_before_repo_read", "handoff discovery is required before repository reads"),
        _check(bool(repo_handoff.get("missing_blocks_deep_read")), "missing_handoff_blocks_deep_read", "missing handoff blocks deep reads"),
    ])

    delegation = collaboration.get("explicit_named_delegation") or {}
    forbidden = set(delegation.get("dispatcher_forbidden_actions") or [])
    required_forbidden = {
        "implement_task_itself",
        "edit_task_files",
        "silently_fallback_to_another_agent",
        "claim_delegate_work_as_own",
        "report_unverified_file_changes",
    }
    checks.extend([
        _check(bool(delegation.get("enabled")), "explicit_delegation_enabled", "explicit named delegation policy is enabled"),
        _check(delegation.get("dispatcher_may_execute_task") is False, "dispatcher_cannot_execute_task", "dispatcher may not execute delegated task"),
        _check(required_forbidden.issubset(forbidden), "relay_only_forbidden_actions_present", "relay-only forbidden actions are configured"),
    ])

    session_contracts = collaboration.get("enforced_session_contracts") or {}
    checks.extend([
        _check(bool(session_contracts.get("enabled")), "session_contracts_enabled", "enforced session contracts are enabled"),
        _check("workspace-entry" in str(session_contracts.get("workspace_entry_command", "")), "workspace_entry_command_registered", "workspace entry command is registered"),
        _check("frontdesk-session" in str(session_contracts.get("frontdesk_session_command", "")), "frontdesk_session_command_registered", "frontdesk session command is registered"),
        _check("role-session" in str(session_contracts.get("role_session_command", "")), "role_session_command_registered", "role session command is registered"),
        _check("artifact-task-plan" in str(session_contracts.get("artifact_task_plan_command", "")), "artifact_task_plan_command_registered", "artifact task plan command is registered"),
    ])

    checks.extend([
        _check(bool(artifact_policy), "artifact_task_policy_present", "artifact task policy is present"),
        _check("ArtifactProducer" in (bindings.get("roles") or {}), "artifact_producer_role_bound", "ArtifactProducer role is bound"),
    ])

    roles = bindings.get("roles") or {}
    workers = bindings.get("workers") or {}
    for role in AGENTLAB_ROLES:
        role_cfg = roles.get(role) or {}
        allowed_workers = role_cfg.get("allowed_workers") or []
        checks.append(_check(bool(allowed_workers), "role_has_allowed_worker", f"{role} has allowed workers"))
        for worker in allowed_workers:
            allowed, reason = check_role_binding(root, worker, role)
            checks.append(_check(allowed, "role_worker_binding_valid", f"{role}/{worker}: {reason}"))

    for worker_id, worker_cfg in workers.items():
        contract = ((contracts.get("contracts") or {}).get(worker_id) or {})
        frontdesk_only = worker_cfg.get("frontdesk_capable") and not worker_cfg.get("worker_capable")
        checks.append(_check(bool(worker_cfg.get("frontdesk_capable") or worker_cfg.get("worker_capable")), "worker_has_profile", f"{worker_id} has at least one profile"))
        if frontdesk_only:
            checks.append(_check(
                contract.get("invocation_style") != "task_packet_prompt",
                "frontdesk_worker_has_no_task_packet_invocation",
                f"{worker_id} frontdesk-only invocation is not task_packet_prompt",
            ))

    agy_info = ((shared_directory.get("agents") or {}).get("agy") or {})
    checks.extend([
        _check(agy_info.get("class") in {"frontdesk_chat_assistant", "frontdesk_and_artifact_cli"}, "agy_registered_as_frontdesk", "agy is registered as a frontdesk-capable agent"),
        _check(
            agy_info.get("may_execute_agentlab_roles_directly") in (False, ["ArtifactProducer"]),
            "agy_cannot_execute_general_roles_directly",
            "agy cannot execute general AgentLab roles directly",
        ),
    ])

    return _doctor_result("protocol_doctor", checks)


def _doctor_result(kind: str, checks: list[ProtocolCheck], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    failed = [c for c in checks if c.status != "pass" and c.severity == "fail"]
    result: dict[str, Any] = {
        "doctor": kind,
        "status": "pass" if not failed else "fail",
        "summary": {
            "checks": len(checks),
            "failed": len(failed),
        },
        "checks": [c.to_dict() for c in checks],
    }
    if extra:
        result.update(extra)
    return result
