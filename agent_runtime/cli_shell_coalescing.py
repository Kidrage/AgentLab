"""Plan same-backend CLI workflow-shell role-session coalescing.

This module does not execute provider or CLI role work. It builds the local
control-plane contract for using one native CLI workflow shell session to
delegate multiple AgentLab roles while preserving per-role receipts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

try:
    from agent_runtime.model_resolver import runtime_provider_for_catalog_model
    from agent_runtime.report_sanitizer import write_report_yaml
except ModuleNotFoundError:  # pragma: no cover - direct script path
    from model_resolver import runtime_provider_for_catalog_model
    from report_sanitizer import write_report_yaml


ROLE_KEY_TO_NAME = {
    "supervisor": "Supervisor",
    "reposcout": "RepoScout",
    "researcher": "Researcher",
    "interface_mapper": "InterfaceMapper",
    "prompt_engineer": "PromptEngineer",
    "coder": "Coder",
    "artifact_producer": "ArtifactProducer",
    "tester_auditor": "TesterAuditor",
    "verifier": "Verifier",
    "archivist": "Archivist",
    "writer": "Writer",
    "reviewer": "Reviewer",
    "scribe": "Scribe",
}

ROLE_ACCEPTANCE_TASKS = {
    "Coder": "Validate the synthetic packet invariants from the Coder role; do not read any project files.",
    "Archivist": "Validate the synthetic receipt and promotion invariants from the Archivist role; do not read any project files.",
    "Supervisor": "Validate the synthetic authority and delegation invariants from the Supervisor role; do not read any project files.",
    "PromptEngineer": "Validate that the synthetic role-result contract is deterministic and role-separated; do not read any project files.",
}

SYNTHETIC_ACCEPTANCE_FIXTURE = {
    "fixture_id": "agentlab-cli-native-surface-smoke-v1",
    "packet_state": "candidate",
    "project_context": "absent",
    "production_promotion": "forbidden",
    "receipt_policy": "one_result_per_delegated_role",
    "validation_policy": "non_empty_findings_and_validation_per_role",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _role_name(role_key: str) -> str:
    return ROLE_KEY_TO_NAME.get(role_key, "".join(part.capitalize() for part in role_key.split("_")))


def _tier_roles(profiles: dict[str, Any], mode: str, tier: str) -> dict[str, Any]:
    modes = profiles.get("modes") if isinstance(profiles.get("modes"), dict) else {}
    mode_cfg = modes.get(mode) if isinstance(modes.get(mode), dict) else {}
    tiers = mode_cfg.get("tiers") if isinstance(mode_cfg.get("tiers"), dict) else {}
    tier_cfg = tiers.get(tier) if isinstance(tiers.get(tier), dict) else {}
    return tier_cfg


def _contract_backend(contract_id: str, contract: dict[str, Any], role_cfg: dict[str, Any]) -> str:
    if contract.get("workflow_shell_backend"):
        return str(contract["workflow_shell_backend"])
    if contract.get("worker_id"):
        return str(contract["worker_id"])
    return str(role_cfg.get("cli_agent") or contract_id)


def _surface(shell: dict[str, Any]) -> dict[str, Any]:
    surface = shell.get("native_command_surface")
    return surface if isinstance(surface, dict) else {}


def _coalescing_surface(shell: dict[str, Any]) -> dict[str, Any]:
    surface = _surface(shell)
    native_subagent = str(surface.get("native_subagent_surface") or "")
    board = str(surface.get("board_surface") or "")
    can_delegate = native_subagent not in {"", "not_registered", "not_declared_by_help"}
    can_board = board not in {"", "not_registered", "not_declared_by_help"}
    return {
        "native_subagent_surface": native_subagent,
        "board_surface": board,
        "can_delegate_with_subagents": can_delegate,
        "can_coordinate_with_board": can_board,
        "coalescing_supported": can_delegate or can_board,
        "coalescing_mode": "native_subagents" if can_delegate else ("board_mediated" if can_board else "not_supported"),
    }


def _role_allowed(role_bindings: dict[str, Any], role: str, worker_id: str) -> bool:
    roles = role_bindings.get("roles") if isinstance(role_bindings.get("roles"), dict) else {}
    role_cfg = roles.get(role) if isinstance(roles.get(role), dict) else {}
    allowed = role_cfg.get("allowed_workers") if isinstance(role_cfg.get("allowed_workers"), list) else []
    return worker_id in {str(item) for item in allowed}


def _model_route(
    role: str,
    role_cfg: dict[str, Any],
    contract: dict[str, Any],
    model_catalog: dict[str, Any],
    model_providers: dict[str, Any],
) -> dict[str, Any]:
    models = model_catalog.get("models") if isinstance(model_catalog.get("models"), dict) else {}
    model_key = str(role_cfg.get("default") or "")
    model = models.get(model_key) if isinstance(models.get(model_key), dict) else {}
    fallback_key = str(role_cfg.get("fallback") or "")
    fallback = models.get(fallback_key) if isinstance(models.get(fallback_key), dict) else {}
    template = str(contract.get("template") or "")
    applied = bool(model_key and "{provider}" in template and "{model_id}" in template)
    provider = runtime_provider_for_catalog_model(model) if model else None
    model_id = model.get("model_id") if model else None
    reasoning_effort = model.get("reasoning_effort") if model else None
    provider_config = (
        model_providers.get(provider) if provider and isinstance(model_providers.get(provider), dict) else {}
    )
    base_url_spec = str(provider_config.get("base_url") or "")
    if base_url_spec.startswith("env:"):
        base_url_parts = base_url_spec.split(":", 2)
        base_url = base_url_parts[2] if len(base_url_parts) == 3 else ""
    else:
        base_url = base_url_spec
    profile_name = f"agentlab{_role_name(role).lower()}" if contract.get("worker_id") == "hermes" else None
    required_profile_config = None
    if profile_name and applied:
        required_profile_config = {
            "model.provider": provider,
            "model.default": model_id,
            "model.base_url": base_url,
            "agent.reasoning_effort": reasoning_effort or "",
            "fallback_providers": [],
        }
    return {
        "configured_model_key": model_key,
        "provider": provider,
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
        "base_url": base_url or None,
        "applied_to_shell_invocation": applied,
        "shell_model_selection": "explicit_catalog_route" if applied else "shell_native_default",
        "fallback_worker": role_cfg.get("fallback_cli_agent"),
        "fallback_invocation_contract": role_cfg.get("fallback_invocation_contract"),
        "fallback_model_key": fallback_key or None,
        "fallback_provider": runtime_provider_for_catalog_model(fallback) if fallback else None,
        "fallback_model_id": fallback.get("model_id") if fallback else None,
        "workflow_shell_profile": profile_name,
        "required_profile_config": required_profile_config,
        "forbidden_profile_config_keys": ["fallback_model"] if profile_name and applied else [],
    }


def _receipt_for_role(shell: dict[str, Any], role: str, model_route: dict[str, Any]) -> dict[str, Any]:
    required_outputs = shell.get("required_outputs") if isinstance(shell.get("required_outputs"), list) else []
    return {
        "role": role,
        "receipt_path": f"role_receipts/{role.lower()}_role_session_receipt.yml",
        "required_outputs": required_outputs,
        "validation_evidence_path": f"role_receipts/{role.lower()}_validation_evidence.yml",
        "model_route": model_route,
    }


def _role_task(role: str) -> dict[str, Any]:
    return {
        "objective": ROLE_ACCEPTANCE_TASKS.get(
            role,
            "Inspect the bounded CLI shell acceptance packet from the assigned AgentLab role and return findings.",
        ),
        "read_scope": [],
        "write_scope": ["returned_artifacts/"],
        "private_project_context_loaded": False,
        "model_file_writes_allowed": False,
        "synthetic_fixture": {**SYNTHETIC_ACCEPTANCE_FIXTURE, "delegated_role": role},
        "production_changes_allowed": False,
        "must_return_finding_artifact": True,
    }


def _execution_contract(group: dict[str, Any]) -> dict[str, Any]:
    backend = str(group.get("backend") or "")
    common = {
        "trusted_runner_required": True,
        "trusted_runner_env": "AGENTLAB_TRUSTED_CLI_SHELL_RUNNER=1",
        "frontdesk_role_invocations": 0,
        "provider_invocation_count_claimed": False,
        "receipts_materialized_by_agentlab_runner": True,
        "acceptance_scope": "synthetic_native_surface_smoke",
        "isolated_execution_workspace_required": True,
        "project_read_tools_allowed": False,
    }
    if backend == "claude_code":
        return {
            **common,
            "native_surface": "claude_inline_agents",
            "coordination_semantics": "single_top_level_shell_invocation",
            "single_provider_session_claimed": False,
            "command_spec": {
                "entrypoint": "claude",
                "arguments": [
                    "--print",
                    "--output-format",
                    "json",
                    "--permission-mode",
                    "plan",
                    "--safe-mode",
                    "--no-session-persistence",
                    "--tools",
                    "Agent",
                    "--agents",
                    "<rendered_inline_agent_json>",
                    "--json-schema",
                    "<role_result_schema>",
                    "<rendered_session_prompt>",
                ],
                "structured_result": "one JSON result containing one section per delegated AgentLab role",
            },
        }
    if backend == "hermes":
        return {
            **common,
            "native_surface": "hermes_kanban",
            "coordination_semantics": "board_orchestrated_multi_worker",
            "single_provider_session_claimed": False,
            "command_spec": {
                "entrypoint": "hermes",
                "command_family": "kanban",
                "board_slug": "agentlab-cli-shell-acceptance",
                "role_task_command": [
                    "kanban",
                    "create",
                    "<role_task_title>",
                    "--body",
                    "<role_task_body>",
                    "--assignee",
                    "<configured_profile_or_default>",
                    "--workspace",
                    "scratch",
                    "--idempotency-key",
                    "<packet_and_role_id>",
                    "--json",
                ],
                "dispatch_command": ["kanban", "dispatch", "--max", "<role_count>", "--json"],
                "collection_commands": [
                    ["kanban", "show", "<task_id>"],
                    ["kanban", "runs", "<task_id>"],
                ],
                "worker_process_note": (
                    "Kanban consolidates AgentLab submission and board governance but may spawn one shell-managed "
                    "worker process per delegated role."
                ),
            },
        }
    return {
        **common,
        "native_surface": "unregistered",
        "coordination_semantics": "unsupported",
        "single_provider_session_claimed": False,
        "command_spec": {"entrypoint": group.get("command")},
    }


def build_cli_shell_coalescing_plan(root: Path, mode: str = "full_cli", tier: str = "performance") -> dict[str, Any]:
    """Build a local plan for coalescing AgentLab roles by workflow shell backend."""
    root = root.resolve()
    profiles_path = root / "config" / "agent_model_profiles.yml"
    contracts_path = root / "config" / "worker_invocation_contracts.yml"
    shells_path = root / "config" / "cli_workflow_shells.yml"
    role_bindings_path = root / "config" / "agent_role_bindings.yml"
    model_catalog_path = root / "config" / "model_catalog.yml"
    model_providers_path = root / "config" / "model_providers.yml"
    profiles = _read_yaml(profiles_path)
    contracts = _read_yaml(contracts_path).get("contracts", {})
    shells = _read_yaml(shells_path).get("shells", {})
    role_bindings = _read_yaml(role_bindings_path)
    model_catalog = _read_yaml(model_catalog_path)
    model_providers = _read_yaml(model_providers_path).get("providers", {})
    tier_roles = _tier_roles(profiles, mode, tier)

    role_sessions: list[dict[str, Any]] = []
    isolated_role_sessions: list[dict[str, str]] = []
    for role_key, role_cfg in tier_roles.items():
        if isinstance(role_cfg, str):
            continue
        if not isinstance(role_cfg, dict) or role_cfg.get("executor_type") != "cli_agent":
            continue
        contract_id = str(role_cfg.get("invocation_contract") or role_cfg.get("cli_agent") or "")
        contract = contracts.get(contract_id) if isinstance(contracts.get(contract_id), dict) else {}
        if contract.get("workflow_shell") is not True:
            continue
        worker_id = str(role_cfg.get("cli_agent") or contract.get("worker_id") or contract_id)
        backend = _contract_backend(contract_id, contract, role_cfg)
        role_name = _role_name(str(role_key))
        if contract.get("coalescing_allowed") is False:
            isolated_role_sessions.append(
                {
                    "role": role_name,
                    "worker_id": worker_id,
                    "invocation_contract": contract_id,
                    "reason": "invocation_contract_requires_isolated_role_session",
                }
            )
            continue
        shell = shells.get(backend) if isinstance(shells.get(backend), dict) else {}
        role_sessions.append(
            {
                "role_key": str(role_key),
                "role": role_name,
                "worker_id": worker_id,
                "backend": backend,
                "invocation_contract": contract_id,
                "command": contract.get("command"),
                "allowed_by_role_binding": _role_allowed(role_bindings, role_name, worker_id),
                "required_receipts": contract.get("required_receipts") or shell.get("required_outputs") or [],
                "model_route": _model_route(
                    str(role_key),
                    role_cfg,
                    contract,
                    model_catalog,
                    model_providers,
                ),
            }
        )

    groups_by_backend: dict[str, list[dict[str, Any]]] = {}
    for session in role_sessions:
        groups_by_backend.setdefault(str(session["backend"]), []).append(session)

    groups: list[dict[str, Any]] = []
    for backend, sessions in sorted(groups_by_backend.items()):
        shell = shells.get(backend) if isinstance(shells.get(backend), dict) else {}
        surface = _coalescing_surface(shell)
        role_receipts = [
            _receipt_for_role(shell, str(session["role"]), session["model_route"])
            for session in sessions
        ]
        coalescing_eligible = len(sessions) > 1 and surface["coalescing_supported"] and all(
            session["allowed_by_role_binding"] for session in sessions
        )
        groups.append(
            {
                "backend": backend,
                "command": shell.get("command") or sessions[0].get("command"),
                "roles": [session["role"] for session in sessions],
                "worker_ids": sorted({str(session["worker_id"]) for session in sessions}),
                "invocation_contracts": sorted({str(session["invocation_contract"]) for session in sessions}),
                "role_count": len(sessions),
                "surface": surface,
                "coalescing_eligible": coalescing_eligible,
                "coalescing_mode": surface["coalescing_mode"] if coalescing_eligible else "separate_role_sessions",
                "role_receipts": role_receipts,
                "single_shell_session_contract": {
                    "packet_path": f"shell_sessions/{backend}_{mode}_{tier}_coalesced_session.yml",
                    "must_return_one_receipt_per_role": True,
                    "shell_state_counts_as_project_memory": False,
                    "agentlab_validation_required_before_acceptance": True,
                    "production_promotion_allowed": False,
                },
                "blocked_reasons": []
                if coalescing_eligible
                else [
                    reason
                    for reason, blocked in (
                        ("needs_at_least_two_roles_for_same_backend", len(sessions) <= 1),
                        ("backend_lacks_registered_subagent_or_board_surface", not surface["coalescing_supported"]),
                        ("one_or_more_roles_not_allowed_for_worker", not all(session["allowed_by_role_binding"] for session in sessions)),
                    )
                    if blocked
                ],
            }
        )

    eligible_groups = [group for group in groups if group["coalescing_eligible"]]
    return {
        "schema_version": 1,
        "report_type": "agentlab_cli_shell_coalescing_plan",
        "root": str(root),
        "status": "pass" if eligible_groups else "candidate",
        "mode": mode,
        "tier": tier,
        "source_configs": {
            "agent_model_profiles": str(profiles_path),
            "worker_invocation_contracts": str(contracts_path),
            "cli_workflow_shells": str(shells_path),
            "agent_role_bindings": str(role_bindings_path),
            "model_catalog": str(model_catalog_path),
            "model_providers": str(model_providers_path),
        },
        "policy": {
            "prefer_same_backend_coalescing": True,
            "coalescing_requires_registered_native_surface": True,
            "per_role_receipts_required": True,
            "shell_state_is_not_project_memory": True,
            "provider_calls_executed": False,
        },
        "role_session_count": len(role_sessions),
        "isolated_role_sessions": isolated_role_sessions,
        "backend_group_count": len(groups),
        "eligible_group_count": len(eligible_groups),
        "groups": groups,
        "acceptance_gate": {
            "runtime_execution_not_performed": True,
            "next_required_evidence": [
                "shell_subagent_delegation_receipt.yml",
                "one role_session_receipt.yml per delegated AgentLab role",
                "local validation evidence per role before AgentLab acceptance",
            ],
        },
    }


def _session_packet_for_group(report: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "packet_type": "agentlab_coalesced_cli_shell_session",
        "backend": group.get("backend"),
        "command": group.get("command"),
        "mode": report.get("mode"),
        "tier": report.get("tier"),
        "coalescing_mode": group.get("coalescing_mode"),
        "provider_calls_executed_by_packet_generation": False,
        "agentlab_authority": {
            "project_memory_authoritative": True,
            "shell_state_counts_as_project_memory": False,
            "production_promotion_allowed": False,
        },
        "task_contract": {
            "task_kind": "cli_shell_native_runtime_acceptance",
            "objective": (
                "Use the registered native shell coordination surface to evaluate an embedded synthetic fixture "
                "and return separate role evidence without reading AgentLab project files."
            ),
            "acceptance_scope": "synthetic_native_surface_smoke",
            "private_project_context_loaded": False,
            "synthetic_input_only": True,
            "production_changes_allowed": False,
            "agentlab_memory_remains_authoritative": True,
        },
        "execution_contract": _execution_contract(group),
        "delegated_roles": [
            {
                "role": receipt.get("role"),
                "receipt_path": receipt.get("receipt_path"),
                "validation_evidence_path": receipt.get("validation_evidence_path"),
                "required_outputs": receipt.get("required_outputs") or [],
                "model_route": receipt.get("model_route") if isinstance(receipt.get("model_route"), dict) else {},
                "task": _role_task(str(receipt.get("role") or "")),
            }
            for receipt in group.get("role_receipts", [])
            if isinstance(receipt, dict)
        ],
        "acceptance_contract": {
            "must_return_one_receipt_per_role": True,
            "must_return_validation_evidence_per_role": True,
            "agentlab_validation_required_before_acceptance": True,
            "shell_subagent_or_board_state_is_operational_only": True,
        },
        "source_plan": "cli_shell_coalescing_plan.yml",
    }


def _materialize_session_packets(root: Path, report_path: Path, report: dict[str, Any]) -> list[str]:
    written: list[str] = []
    base = report_path.parent
    for group in report.get("groups", []):
        if not isinstance(group, dict) or group.get("coalescing_eligible") is not True:
            continue
        contract = group.get("single_shell_session_contract") if isinstance(group.get("single_shell_session_contract"), dict) else {}
        packet_text = str(contract.get("packet_path") or "")
        if not packet_text:
            continue
        packet_path = base / packet_text
        packet = _session_packet_for_group(report, group)
        write_report_yaml(packet_path, packet, root)
        written.append(_rel_path(root, packet_path))
    return written


def write_cli_shell_coalescing_plan(root: Path, out: Path, mode: str = "full_cli", tier: str = "performance") -> dict[str, Any]:
    root = root.resolve()
    out = out if out.is_absolute() else root / out
    report = build_cli_shell_coalescing_plan(root, mode=mode, tier=tier)
    materialized = _materialize_session_packets(root, out, report)
    report["materialized_session_packets"] = materialized
    expected_packets = [
        _rel_path(root, out.parent / group["single_shell_session_contract"]["packet_path"])
        for group in report.get("groups", [])
        if isinstance(group, dict)
        and group.get("coalescing_eligible") is True
        and isinstance(group.get("single_shell_session_contract"), dict)
        and group["single_shell_session_contract"].get("packet_path")
    ]
    report["missing_session_packets"] = [path for path in expected_packets if path not in set(materialized)]
    report["status"] = "pass" if report.get("eligible_group_count", 0) > 0 and not report["missing_session_packets"] else "candidate"
    write_report_yaml(out, report, root)
    return report
