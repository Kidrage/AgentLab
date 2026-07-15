"""Audit frontdesk/operator boundaries for AgentLab live work."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from report_sanitizer import write_report_yaml


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _worker(root: Path, worker_id: str) -> dict[str, Any]:
    bindings = _read_yaml(root / "config" / "agent_role_bindings.yml")
    return ((bindings.get("workers") or {}).get(worker_id) or {}) if bindings else {}


def _role(root: Path, role_id: str) -> dict[str, Any]:
    bindings = _read_yaml(root / "config" / "agent_role_bindings.yml")
    return ((bindings.get("roles") or {}).get(role_id) or {}) if bindings else {}


def _artifact_backend_bindings(root: Path) -> list[dict[str, Any]]:
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml")
    bindings: list[dict[str, Any]] = []

    def visit(node: Any, path: list[str]) -> None:
        if isinstance(node, dict):
            backend = node.get("artifact_backend")
            agent = path[-1] if path else "unknown"
            if backend:
                bindings.append(
                    {
                        "path": ".".join(path),
                        "agent_profile": agent,
                        "artifact_backend": backend,
                    }
                )
            for key, value in node.items():
                visit(value, [*path, str(key)])
        elif isinstance(node, list):
            for index, value in enumerate(node):
                visit(value, [*path, str(index)])

    visit(profiles, [])
    return bindings


def build_frontdesk_boundary_audit(root: Path, frontdesk_agent: str = "hermes") -> dict[str, Any]:
    """Build a deterministic audit of the frontdesk/role-worker boundary."""
    root = root.resolve()
    frontdesk_policy = _read_yaml(root / "config" / "frontdesk_policy.yml")
    cli_policy = _read_yaml(root / "config" / "cli_entrypoint_policy.yml")
    media_backends = _read_yaml(root / "config" / "media_generation_backends.yml")
    workflow_shells = _read_yaml(root / "config" / "cli_workflow_shells.yml")
    profiles = _read_yaml(root / "config" / "agent_model_profiles.yml")
    role_bindings = _read_yaml(root / "config" / "agent_role_bindings.yml")
    invocation_contracts = _read_yaml(
        root / "config" / "worker_invocation_contracts.yml"
    )
    model_catalog = _read_yaml(root / "config" / "model_catalog.yml")
    runtime_registry = _read_yaml(root / "config" / "runtime_registry.yml")
    capability_cli = _read_text(root / "agent_runtime" / "cli" / "capability_contracts.py")
    narrative_cli = _read_text(root / "agent_runtime" / "cli" / "narrative_eval.py")
    narrative_runtime = _read_text(root / "agent_runtime" / "narrative_eval.py")

    worker = _worker(root, frontdesk_agent)
    codex_worker = _worker(root, "codex")
    researcher_role = _role(root, "Researcher")
    artifact_role = _role(root, "ArtifactProducer")
    grok_worker = _worker(root, "grok")
    hermes_worker = _worker(root, "hermes")
    claude_worker = _worker(root, "claude_code")
    hermes_grok = ((media_backends.get("backends") or {}).get("hermes_grok_oauth") or {})
    contracts = invocation_contracts.get("contracts") or {}
    grok_research_contract = contracts.get("grok_research") or {}
    grok_media_contract = contracts.get("grok_media") or {}
    shell_registry = workflow_shells.get("shells") if isinstance(workflow_shells.get("shells"), dict) else {}
    mode_policy = (
        workflow_shells.get("mode_policy")
        if isinstance(workflow_shells.get("mode_policy"), dict)
        else {}
    )
    shell_boundary = (
        workflow_shells.get("boundary")
        if isinstance(workflow_shells.get("boundary"), dict)
        else {}
    )
    capability_families = (
        workflow_shells.get("capability_families")
        if isinstance(workflow_shells.get("capability_families"), dict)
        else {}
    )
    required_shell_families = {
        "one_shot_role_execution",
        "tool_and_mcp_governance",
        "skills_plugins_and_bundles",
        "structured_output_and_qc",
    }
    full_cli = (((profiles.get("modes") or {}).get("full_cli") or {}).get("tiers") or {})

    def collect_full_cli_shells(node: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(node, dict):
            cli_agent = node.get("cli_agent")
            if cli_agent:
                found.add(str(cli_agent))
            if node.get("artifact_backend") == "hermes_grok_oauth":
                found.add("grok")
            if node.get("fallback_artifact_backend") == "hermes_grok_oauth":
                found.add("grok")
            for value in node.values():
                found.update(collect_full_cli_shells(value))
        elif isinstance(node, list):
            for value in node:
                found.update(collect_full_cli_shells(value))
        return found

    full_cli_shells = collect_full_cli_shells(full_cli)
    runtime_boundary = frontdesk_policy.get("external_runtime_boundary") or {}
    default_frontdesk = frontdesk_policy.get("default_frontdesk") or {}
    execution_paths = frontdesk_policy.get("execution_paths") or {}
    direct_closed_loop = execution_paths.get("direct_closed_loop") or {}
    routed_task_intake = execution_paths.get("routed_task_intake") or {}
    catalog_models = model_catalog.get("models") or {}
    artifact_backend_bindings = _artifact_backend_bindings(root)
    grok_artifact_bindings = [
        item for item in artifact_backend_bindings if item.get("artifact_backend") == "hermes_grok_oauth"
    ]
    runtime_providers = runtime_registry.get("providers") if isinstance(runtime_registry.get("providers"), dict) else {}
    runtime_models = runtime_registry.get("models") if isinstance(runtime_registry.get("models"), dict) else {}
    grok_runtime_quarantined = (
        (runtime_providers.get("xai_oauth") or {}).get("status") == "quarantined"
        and (runtime_models.get("grok_4_3_oauth_quarantined") or {}).get("status") == "quarantined"
    )

    checks = [
        {
            "id": "frontdesk_policy_declares_non_worker_boundary",
            "status": "pass"
            if "implement_task_itself" in (frontdesk_policy.get("forbidden_actions") or [])
            and "invoke_registered_agent_via_agentlab_contract" in (frontdesk_policy.get("allowed_actions") or [])
            else "fail",
            "evidence": ["config/frontdesk_policy.yml"],
            "summary": "frontdesk may invoke registered agents by contract but may not implement tasks itself",
        },
        {
            "id": "configured_frontdesk_has_entrypoint",
            "status": "pass"
            if frontdesk_agent in (frontdesk_policy.get("frontdesk_agents") or {})
            and frontdesk_agent in (cli_policy.get("agents") or {})
            else "fail",
            "evidence": ["config/frontdesk_policy.yml", "config/cli_entrypoint_policy.yml"],
            "summary": f"{frontdesk_agent} has a frontdesk session entrypoint",
        },
        {
            "id": "hermes_deepseek_v4_pro_is_default_frontdesk",
            "status": "pass"
            if frontdesk_agent == "hermes"
            and default_frontdesk.get("agent_id") == "hermes"
            and default_frontdesk.get("provider") == "deepseek"
            and default_frontdesk.get("model_key") == "deepseek_v4_pro"
            and default_frontdesk.get("model_id") == "deepseek-v4-pro"
            and "deepseek_v4_pro" in catalog_models
            else "fail",
            "evidence": ["config/frontdesk_policy.yml", "config/model_catalog.yml"],
            "summary": "Hermes CLI with DeepSeek V4 Pro is the canonical AgentLab frontdesk",
        },
        {
            "id": "frontdesk_profile_is_separate_from_role_sessions",
            "status": "pass"
            if worker.get("frontdesk_capable") is True
            and "frontdesk_gateway" in (worker.get("worker_capabilities") or [])
            and "role_worker" in (worker.get("worker_capabilities") or [])
            and (role_bindings.get("enforcement") or {}).get("forbid_frontdesk_profile_as_worker") is True
            and ((role_bindings.get("roles") or {}).get("Supervisor") or {}).get("required_session") is True
            else "fail",
            "evidence": ["config/agent_role_bindings.yml"],
            "summary": "Hermes may be FrontDesk or a role worker, but never both in the same session",
        },
        {
            "id": "codex_is_external_worker_not_frontdesk",
            "status": "pass"
            if codex_worker.get("frontdesk_capable") is False
            and "frontdesk_gateway" not in (codex_worker.get("worker_capabilities") or [])
            and "codex" not in (frontdesk_policy.get("frontdesk_agents") or {})
            else "fail",
            "evidence": ["config/frontdesk_policy.yml", "config/agent_role_bindings.yml"],
            "summary": "Codex is an external AgentLab construction/audit worker, not an internal FrontDesk",
        },
        {
            "id": "direct_closed_loop_does_not_require_frontdesk",
            "status": "pass"
            if direct_closed_loop.get("frontdesk_required") is False
            and {"run-pipeline", "role-session", "narrative-eval"}.issubset(
                set(direct_closed_loop.get("entrypoints") or [])
            )
            and routed_task_intake.get("frontdesk_agent") == "hermes"
            else "fail",
            "evidence": ["config/frontdesk_policy.yml"],
            "summary": "AgentLab can validate a declared pipeline directly without creating a FrontDesk session",
        },
        {
            "id": "sandbox_approval_is_external_runtime_boundary",
            "status": "pass"
            if runtime_boundary.get("sandbox_approvals_are_agentlab_roles") is False
            and runtime_boundary.get("sandbox_approvals_are_agentlab_workflow_nodes") is False
            else "fail",
            "evidence": ["config/frontdesk_policy.yml"],
            "summary": "host/Codex sandbox approval is not an AgentLab role or workflow node",
        },
        {
            "id": "media_live_role_owner_is_artifact_producer",
            "status": "pass"
            if "grok" in (artifact_role.get("allowed_workers") or [])
            and artifact_role.get("required_session") is True
            else "fail",
            "evidence": ["config/agent_role_bindings.yml"],
            "summary": "ArtifactProducer is the media/artifact role owner and can be assigned to grok",
        },
        {
            "id": "local_grok_cli_backend_is_registered_internal_backend",
            "status": "pass"
            if hermes_grok.get("adapter_kind") in {"local_grok_cli", "grok_cli_oauth"}
            and hermes_grok.get("execution_mode") == "orchestrated_worker"
            and hermes_grok.get("worker_id") == "grok"
            and hermes_grok.get("role_owner") == "ArtifactProducer"
            and hermes_grok.get("internal_worker") is True
            else "fail",
            "evidence": ["config/media_generation_backends.yml"],
            "summary": "Hermes/Grok is registered as an internal ArtifactProducer-owned local Grok CLI backend",
        },
        {
            "id": "cli_workflow_shell_registry_covers_hermes_and_claude",
            "status": "pass"
            if {"hermes", "claude_code"}.issubset(set(shell_registry))
            and required_shell_families.issubset(set(capability_families))
            and shell_boundary.get("shells_do_not_create_agentlab_roles") is True
            and shell_boundary.get("shells_must_return_agentlab_receipts") is True
            else "fail",
            "evidence": ["config/cli_workflow_shells.yml"],
            "summary": (
                "CLI workflow shell registry covers Hermes and Claude Code command families while keeping "
                "AgentLab role/session/memory/promotion authority outside the shell"
            ),
        },
        {
            "id": "cli_workflow_shell_governance_covers_full_cli_mode",
            "status": "pass"
            if full_cli_shells
            and full_cli_shells.issubset(set(shell_registry))
            and ((mode_policy.get("full_cli") or {}).get("primary_governance_object") == "cli_shell_capability_and_delivery")
            and ((mode_policy.get("full_cli") or {}).get("own_workflow_shell_scaffold") is False)
            and ((mode_policy.get("full_api") or {}).get("primary_governance_object") == "agentlab_internal_work_shell")
            and ((mode_policy.get("full_api") or {}).get("own_workflow_shell_scaffold") is True)
            else "fail",
            "evidence": ["config/cli_workflow_shells.yml", "config/agent_model_profiles.yml"],
            "summary": (
                "full_cli governs selected CLI shell capabilities/delivery instead of rebuilding shell scaffolds; "
                f"full_cli_shells={sorted(full_cli_shells)}"
            ),
        },
        {
            "id": "workflow_shell_workers_are_bounded_role_workers",
            "status": "pass"
            if full_cli_shells
            and all(
                "workflow_shell" in (_worker(root, shell_id).get("worker_capabilities") or [])
                for shell_id in full_cli_shells
            )
            and "workflow_shell" in (hermes_worker.get("worker_capabilities") or [])
            and "role_worker" in (hermes_worker.get("worker_capabilities") or [])
            and hermes_worker.get("frontdesk_capable") is True
            and "frontdesk_gateway" in (hermes_worker.get("worker_capabilities") or [])
            and "workflow_shell" in (claude_worker.get("worker_capabilities") or [])
            and "role_worker" in (claude_worker.get("worker_capabilities") or [])
            and claude_worker.get("frontdesk_capable") is False
            else "fail",
            "evidence": ["config/agent_role_bindings.yml", "config/cli_workflow_shells.yml"],
            "summary": "Hermes and Claude Code remain bounded role-session shells; Hermes FrontDesk is a separate profile",
        },
        {
            "id": "hermes_grok_backend_uses_workflow_shell_without_role_leakage",
            "status": "pass"
            if hermes_grok.get("execution_kernel") == "hermes_workflow_shell"
            and hermes_grok.get("orchestration_scope") == "bounded_role_session_backend"
            and hermes_grok.get("worker_id") == "grok"
            and hermes_grok.get("role_owner") == "ArtifactProducer"
            and ((hermes_grok.get("agentlab_boundary") or {}).get("shell_state_is_not_project_memory") is True)
            else "fail",
            "evidence": ["config/media_generation_backends.yml", "config/cli_workflow_shells.yml"],
            "summary": "Hermes workflow shell powers the Grok media backend, but ArtifactProducer/grok remains the AgentLab role-worker owner",
        },
        {
            "id": "grok_cli_is_registered_as_internal_research_and_artifact_worker",
            "status": "pass"
            if "grok" in (researcher_role.get("allowed_workers") or [])
            and "grok" in (artifact_role.get("allowed_workers") or [])
            and grok_worker.get("worker_capable") is True
            and grok_worker.get("frontdesk_capable") is False
            and "candidate_artifact_worker" in (grok_worker.get("worker_capabilities") or [])
            and set(grok_worker.get("allowed_roles") or []) == {
                "Researcher",
                "ArtifactProducer",
            }
            and "Coder" in (grok_worker.get("forbidden_roles") or [])
            and "Writer" in (grok_worker.get("forbidden_roles") or [])
            else "fail",
            "evidence": ["config/agent_role_bindings.yml", "config/worker_invocation_contracts.yml"],
            "summary": "Grok is a bounded internal Researcher and ArtifactProducer worker, never a Writer, Coder, or FrontDesk",
        },
        {
            "id": "grok_current_contracts_use_hermes_surface",
            "status": "pass"
            if grok_research_contract.get("worker_id") == "grok"
            and grok_research_contract.get("command") == "hermes"
            and grok_research_contract.get("invocation_style")
            == "sourced_research_task_packet"
            and grok_media_contract.get("worker_id") == "grok"
            and grok_media_contract.get("command") == "hermes"
            and grok_media_contract.get("invocation_style")
            == "media_backend_task_packet"
            else "fail",
            "evidence": ["config/worker_invocation_contracts.yml"],
            "summary": "grok_research and grok_media are separate role contracts on the configured Hermes xAI OAuth executable",
        },
        {
            "id": "quarantined_grok_is_not_a_default_artifact_profile",
            "status": "pass" if grok_runtime_quarantined and not grok_artifact_bindings else "fail",
            "evidence": ["config/runtime_registry.yml", "config/agent_model_profiles.yml"],
            "summary": (
                "Grok remains registered for explicit bounded contracts but is quarantined from default "
                f"artifact profiles; default bindings={len(grok_artifact_bindings)}"
            ),
        },
        {
            "id": "raw_media_live_cli_requires_role_session",
            "status": "pass"
            if 'command("media-backend-execute")' in capability_cli
            and "--live" in capability_cli
            and "--role-session" in capability_cli
            and "missing_role_session" in _read_text(root / "agent_runtime" / "media_backend_adapter.py")
            else "warn",
            "evidence": ["agent_runtime/cli/capability_contracts.py"],
            "summary": "raw media-backend-execute --live requires ArtifactProducer role-session evidence",
        },
        {
            "id": "narrative_live_eval_requires_writer_role_session",
            "status": "pass"
            if "--writer-worker" in narrative_cli
            and "validate_narrative_live_role_session" in narrative_runtime
            and "missing_role_session" in narrative_runtime
            else "warn",
            "evidence": ["agent_runtime/cli/narrative_eval.py", "agent_runtime/narrative_eval.py"],
            "summary": "narrative-eval live requires Writer role-session evidence",
        },
    ]
    fail_count = sum(1 for check in checks if check["status"] == "fail")
    warn_count = sum(1 for check in checks if check["status"] == "warn")
    status = "fail" if fail_count else ("warn" if warn_count else "pass")
    conclusion = (
        "Hermes CLI with DeepSeek V4 Pro is the canonical FrontDesk for routed intake, while declared pipelines "
        "may run directly without FrontDesk. Role execution still requires role-session evidence. Registered CLI "
        "workflow-shell capabilities are absorbed as bounded role-session execution shells, while AgentLab "
        "keeps ownership of project memory, validation, receipts, and promotion."
    )
    return {
        "schema_version": 1,
        "report_type": "agentlab_frontdesk_boundary_audit",
        "root": str(root),
        "frontdesk_agent": frontdesk_agent,
        "status": status,
        "conclusion": conclusion,
        "intended_chain": [
            f"{frontdesk_agent} / DeepSeek V4 Pro: optional frontdesk-session for task intake and routing",
            "Direct closed loop: AgentLab pipeline or role-session without FrontDesk",
            "Supervisor: route and mission contract",
            "Researcher: Grok sourced research through grok_research role-session",
            "ArtifactProducer: media/artifact production role-session",
            "Writer: narrative live eval role-session",
            "Registered CLI workflow shells: native capability families inside bounded role sessions",
            "hermes_grok_oauth: configured Hermes executable behind separate grok_research and grok_media contracts",
            "TesterAuditor/Verifier: audit generated candidate artifacts",
        ],
        "operator_boundary": {
            "allowed": [
                "frontdesk-session",
                "prepare/create task",
                "inspect run artifacts",
                "read role receipts and error reports",
            ],
            "external_runtime_boundary": [
                "request host sandbox approval when the local runtime requires it",
                "treat sandbox approval as outside AgentLab's production chain",
            ],
            "not_allowed_as_frontdesk": [
                "implement task content directly",
                "execute live provider adapter commands as the production path",
                "claim backend output as AgentLab role output without a role-session receipt",
            ],
        },
        "checks": checks,
        "issues": [
            check["summary"]
            for check in checks
            if check["status"] in {"fail", "warn"}
        ],
    }


def write_frontdesk_boundary_audit(
    root: Path,
    out: Path,
    frontdesk_agent: str = "hermes",
) -> dict[str, Any]:
    report = build_frontdesk_boundary_audit(root, frontdesk_agent=frontdesk_agent)
    write_report_yaml(out, report, root)
    return report
