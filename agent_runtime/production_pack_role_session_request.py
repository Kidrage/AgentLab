"""Build a safe fresh-run request for production-pack role acceptance."""

from __future__ import annotations

import hashlib
import os
import shlex
from pathlib import Path
from typing import Any

try:
    from agent_runtime.cli_executor import resolve_cli_profile
    from agent_runtime.config_loader import load_agentlab_configs
    from agent_runtime.outbound_context import (
        PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
        build_outbound_context_manifest,
    )
    from agent_runtime.policies import ensure_safe_task_id
    from agent_runtime.protocols.enforcement import check_role_binding
    from agent_runtime.report_sanitizer import write_report_yaml
    from agent_runtime.workflow_plan import build_workflow_plan
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from cli_executor import resolve_cli_profile
    from config_loader import load_agentlab_configs
    from outbound_context import (
        PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
        build_outbound_context_manifest,
    )
    from policies import ensure_safe_task_id
    from protocols.enforcement import check_role_binding
    from report_sanitizer import write_report_yaml
    from workflow_plan import build_workflow_plan


DEFAULT_PROJECT = "AgentLab"
DEFAULT_SOURCE_TASK_ID = "task_production_pack_role_session_live_20260710"
DEFAULT_TARGET_TASK_ID = (
    "task_production_pack_role_session_governed_20260710_01"
)
ROLE_CHAIN = ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
ROLE_KEYS = {
    "Supervisor": "supervisor",
    "Researcher": "researcher",
    "ArtifactProducer": "artifact_producer",
    "Verifier": "verifier",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative_path(root: Path, path: Path) -> str | None:
    try:
        return path.resolve(strict=False).relative_to(root).as_posix()
    except ValueError:
        return None


def _role_surfaces(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    configs = load_agentlab_configs(root)
    profiles = configs.get("agent_model_profiles", {})
    surfaces: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for role in ROLE_CHAIN:
        profile = resolve_cli_profile(
            profiles,
            ROLE_KEYS[role],
            budget_mode="max_quality",
            mode="full_cli",
        )
        if not profile:
            issues.append(f"missing_full_cli_profile:{role}")
            continue
        worker = str(profile.get("cli_agent") or "")
        allowed, reason = check_role_binding(root, worker, role)
        if not allowed:
            issues.append(f"role_binding_denied:{role}:{worker}")
        surfaces[role] = {
            "executor_type": "cli_agent",
            "worker": worker,
            "invocation_contract": profile.get("invocation_contract"),
            "model_key": profile.get("default"),
            "role_binding_allowed": allowed,
            "role_binding_reason": reason,
            "silent_fallback_allowed": False,
        }
    return surfaces, issues


def _script_text(
    request: dict[str, Any],
    root: Path,
    audit_path: Path,
    script_path: Path,
) -> str:
    project = str(request["project"])
    target_task_id = str(request["target_task_id"])
    root_from_script = os.path.relpath(root, script_path.resolve().parent)
    source_request = str(request["source_request_path"])
    target_run = str(request["target_run_dir"])
    try:
        audit_relative = audit_path.resolve().relative_to(root).as_posix()
        audit_assignment = f'"$ROOT/{audit_relative}"'
    except ValueError:
        audit_assignment = shlex.quote(str(audit_path))
    q = shlex.quote
    return f"""#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/{root_from_script}" && pwd)"
SOURCE_REQUEST="$ROOT/{source_request}"
TARGET_RUN="$ROOT/{target_run}"
AUDIT_OUT={audit_assignment}

if [[ "${{{PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME}:-}}" != "1" ]]; then
  echo "blocked: set {PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME}=1 only after explicit informed approval" >&2
  exit 2
fi
if [[ -e "$TARGET_RUN" ]]; then
  echo "blocked: target run already exists: $TARGET_RUN" >&2
  exit 3
fi

cd "$ROOT"
export AGENTLAB_MODE=full_cli

./agentlab.sh init-task \
  --project {q(project)} \
  --task-id {q(target_task_id)} \
  --request-file "$SOURCE_REQUEST" \
  --no-auto-slug

./agentlab.sh prepare \
  --project {q(project)} \
  --task-id {q(target_task_id)} \
  --budget max-quality \
  --write-plan

test -s "$TARGET_RUN/mission_contract.yml"
test -s "$TARGET_RUN/workflow_plan.yml"

./agentlab.sh run-pipeline \
  --project {q(project)} \
  --task-id {q(target_task_id)} \
  --budget max-quality \
  --execute

./agentlab.sh production-pack-role-session-audit \
  --project {q(project)} \
  --task-id {q(target_task_id)} \
  --out "$AUDIT_OUT" \
  --require-pass
"""


def build_production_pack_role_session_request(
    root: Path,
    *,
    project: str = DEFAULT_PROJECT,
    source_task_id: str = DEFAULT_SOURCE_TASK_ID,
    target_task_id: str = DEFAULT_TARGET_TASK_ID,
) -> dict[str, Any]:
    """Build a content-free request without executing any provider."""
    root = root.resolve()
    issues: list[str] = []
    for task_id in (source_task_id, target_task_id):
        try:
            ensure_safe_task_id(task_id)
        except Exception:
            issues.append(f"unsafe_task_id:{task_id}")

    source_run = root / "projects" / project / "runs" / source_task_id
    source_request = source_run / "user_request.md"
    target_run = root / "projects" / project / "runs" / target_task_id
    source_relative = _relative_path(root, source_request)
    target_relative = _relative_path(root, target_run)
    if source_relative is None:
        issues.append("source_request_outside_agentlab_root")
    if target_relative is None:
        issues.append("target_run_outside_agentlab_root")
    if not source_request.is_file():
        issues.append("source_request_missing")
        request_text = ""
    else:
        request_text = source_request.read_text(encoding="utf-8")
        if not request_text.strip():
            issues.append("source_request_empty")
    if target_run.exists():
        issues.append("target_run_already_exists")

    context_preflight = build_outbound_context_manifest(
        root,
        item_id=target_task_id,
        role="ProductionPackRoleChain",
        provider_surface="none:local_request_preflight",
        payload_kind="production_pack_request_source_preview",
        payload_text=request_text,
        source_paths=[source_request] if source_request.is_file() else [],
        private_context=True,
        exact_payload=True,
        sealed_context=True,
        execution_workspace_isolated=True,
        approval_required=False,
        approval_granted=False,
        approval_env_name=PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
        source_inventory_required=True,
    )
    if not context_preflight.get("execution_allowed"):
        issues.extend(
            f"source_context:{issue}"
            for issue in context_preflight.get("issues", [])
        )

    plan = build_workflow_plan(
        root,
        project,
        target_task_id,
        user_request_path=source_request,
        budget_mode="max_quality",
    )
    if (plan.production_pack or {}).get("status") != "synthesis_candidate":
        issues.append("route_is_not_production_pack_synthesis_candidate")
    if plan.route.agents != ROLE_CHAIN:
        issues.append("role_chain_mismatch")
    if not plan.mission_contract:
        issues.append("mission_contract_preview_missing")
    if plan.mission_contract.get("compiler_source") != "rule_based":
        issues.append("mission_contract_preview_not_deterministic")

    role_surfaces, surface_issues = _role_surfaces(root)
    issues.extend(surface_issues)
    source_sha256 = _sha256(source_request) if source_request.is_file() else None
    return {
        "schema_version": 1,
        "report_type": "agentlab_production_pack_role_session_request",
        "status": "ready_for_explicit_approval" if not issues else "fail",
        "project": project,
        "source_task_id": source_task_id,
        "target_task_id": target_task_id,
        "source_request_path": source_relative,
        "source_request_sha256": source_sha256,
        "source_request_contents_rendered": False,
        "target_run_dir": target_relative,
        "fresh_run_required": True,
        "provider_calls_executed": False,
        "role_chain": ROLE_CHAIN,
        "role_surfaces": role_surfaces,
        "route_preview": {
            "route_key": plan.route.route_key,
            "agents": plan.route.agents,
            "production_pack_status": (plan.production_pack or {}).get("status"),
            "production_pack_id": (plan.production_pack or {}).get("pack_id"),
            "mission_compiler_source": plan.mission_contract.get(
                "compiler_source"
            ),
        },
        "approval": {
            "required": True,
            "env_name": PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME,
            "observed_during_request": (
                os.getenv(PRODUCTION_PACK_CONTEXT_APPROVAL_ENV_NAME) == "1"
            ),
            "scope": "production_pack_four_role_minimal_context_only",
            "env_value_rendered": False,
        },
        "context_boundary": {
            "packet_only": True,
            "workspace_scan_allowed": False,
            "workspace_mutation_allowed": False,
            "exact_runtime_manifest_required_for_every_role": True,
            "secret_pattern_gate_before_every_provider_call": True,
            "silent_provider_fallback_allowed": False,
        },
        "source_context_preflight": {
            "status": context_preflight.get("status"),
            "payload": context_preflight.get("payload"),
            "source_inventory": context_preflight.get("source_inventory"),
            "issues": context_preflight.get("issues") or [],
        },
        "required_run_artifacts": [
            "mission_contract.yml",
            "workflow_plan.yml",
            "01_supervisor_plan.md",
            "domain_research_brief.md",
            "production_pack_research_contract.yml",
            "production_pack_proposal.yml",
            "domain_memory_contract.yml",
            "lifecycle_profile.yml",
            "production_pack_output_contract.yml",
            "verification_report.md",
            "production_pack_verification_receipt.yml",
            *[
                f"outbound_context_manifest_{role.lower()}.yml"
                for role in ROLE_CHAIN
            ],
        ],
        "candidate_only": True,
        "production_modified": False,
        "promotion_attempted": False,
        "runner_script": None,
        "audit_report": None,
        "issues": sorted(set(issues)),
    }


def write_production_pack_role_session_request(
    root: Path,
    out: Path,
    *,
    project: str = DEFAULT_PROJECT,
    source_task_id: str = DEFAULT_SOURCE_TASK_ID,
    target_task_id: str = DEFAULT_TARGET_TASK_ID,
) -> dict[str, Any]:
    root = root.resolve()
    request = build_production_pack_role_session_request(
        root,
        project=project,
        source_task_id=source_task_id,
        target_task_id=target_task_id,
    )
    out = out if out.is_absolute() else root / out
    script_path = out.with_suffix(".sh")
    audit_path = out.with_name(f"{out.stem}_audit.yml")
    if request.get("status") == "ready_for_explicit_approval":
        request["runner_script"] = str(script_path)
        request["audit_report"] = str(audit_path)
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            _script_text(request, root, audit_path, script_path),
            encoding="utf-8",
        )
        script_path.chmod(0o700)
    write_report_yaml(out, request, root)
    return request
