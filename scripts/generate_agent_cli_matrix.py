#!/usr/bin/env python3
"""Generate copyable CSV views from AgentLab's authoritative YAML registries."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Any

import yaml

try:
    from agent_runtime.role_keys import canonical_role_name
except ModuleNotFoundError:  # pragma: no cover - direct script path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from agent_runtime.role_keys import canonical_role_name


def _read_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return data


def _runtime_provider(model: dict[str, Any]) -> str:
    if model.get("runtime_provider"):
        return str(model["runtime_provider"])
    provider = str(model.get("provider") or "")
    model_id = str(model.get("model_id") or "")
    if provider == "deepseek_official":
        return "deepseek"
    if provider in {"dashscope_cn", "dashscope_intl"}:
        if model_id.startswith("qwen3-coder"):
            return "qwen-coder"
        if "flash" in model_id:
            return "qwen-flash"
        if model_id.startswith(("qwen3.7", "qwen-max", "qwen3-max")):
            return "qwen3"
        return "qwen"
    if provider == "qwen_token_plan":
        return "tokenplan-qwen"
    return provider


def _join(values: list[str] | tuple[str, ...] | None) -> str:
    return " | ".join(str(value) for value in (values or []))


def _artifact_dispatch_summary(
    policy: dict[str, Any],
    *,
    tier: str,
) -> tuple[str, str, list[tuple[str, dict[str, Any]]]]:
    """Return effective ArtifactTask dispatch rather than one generic profile."""
    artifact_types = policy.get("artifact_types") or {}
    providers = policy.get("providers") or {}
    grouped: dict[
        tuple[str, str, str, str],
        list[str],
    ] = {}
    selected_rows: list[tuple[str, dict[str, Any]]] = []
    capacity_tier = {"max_quality": "full", "max-quality": "full"}.get(
        tier,
        tier,
    )
    for artifact_type, artifact_config in artifact_types.items():
        required = set((artifact_config or {}).get("required_capabilities") or [])
        eligible: list[tuple[int, str, dict[str, Any]]] = []
        for provider_id, provider_config in providers.items():
            if capacity_tier == "alter" and provider_id != "hermes_grok":
                continue
            handles = set((provider_config or {}).get("handles") or [])
            capabilities = set(
                (provider_config or {}).get("capabilities") or []
            )
            if artifact_type not in handles and "mixed" not in handles:
                continue
            if not required.issubset(capabilities):
                continue
            eligible.append(
                (
                    int((provider_config or {}).get("priority", 0)),
                    str(provider_id),
                    provider_config or {},
                )
            )
        eligible.sort(key=lambda item: item[0], reverse=True)
        if not eligible:
            grouped.setdefault(("unsupported", "", "", ""), []).append(
                str(artifact_type)
            )
            continue
        _, provider_id, provider_config = eligible[0]
        capacity_route = str(
            ((provider_config.get("capacity_routes") or {}).get(capacity_tier))
            or ""
        )
        key = (
            provider_id,
            str(provider_config.get("worker") or ""),
            str(provider_config.get("invocation_contract") or ""),
            capacity_route,
        )
        grouped.setdefault(key, []).append(str(artifact_type))
        selected_rows.append((str(artifact_type), provider_config))

    parts: list[str] = []
    for (provider_id, worker, contract, capacity_route), types in grouped.items():
        joined_types = "|".join(types)
        if provider_id == "unsupported":
            parts.append(f"{joined_types}=>unsupported")
        else:
            parts.append(
                f"{joined_types}=>{provider_id}/{worker}/{contract}/{capacity_route}"
            )
    return _join(list(artifact_types)), "; ".join(parts), selected_rows


def build_matrices(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    config = root / "config"
    profiles = _read_yaml(config / "agent_model_profiles.yml")
    catalog_config = _read_yaml(config / "model_catalog.yml")
    catalog = catalog_config.get("models") or {}
    catalog_providers = catalog_config.get("providers") or {}
    capacity = _read_yaml(config / "model_capacity.yml")
    capacity_routes = capacity.get("routes") or {}
    capacity_pools = capacity.get("pools") or {}
    contracts = (_read_yaml(config / "worker_invocation_contracts.yml").get("contracts") or {})
    bindings = _read_yaml(config / "agent_role_bindings.yml")
    requirements = _read_yaml(config / "runtime_cli_requirements.yml")
    artifact_policy = _read_yaml(config / "artifact_task_policy.yml")
    workers = bindings.get("workers") or {}
    roles = bindings.get("roles") or {}
    components = requirements.get("components") or {}

    errors: list[str] = []
    matrix_rows: list[dict[str, str]] = []
    required_performance_routes = {
        "supervisor": (
            "claude_code",
            "claude_supervisor_fallback",
            "deepseek_v4_pro",
        ),
        "reposcout": ("claude_code", "claude", "deepseek_v4_pro"),
        "interface_mapper": ("claude_code", "claude", "deepseek_v4_pro"),
        "narrative_planner": (
            "agy",
            "agy_narrative_planner",
            "gemini_3_6_flash_high_agy_oauth",
        ),
        "tester_auditor": ("claude_code", "claude", "deepseek_v4_pro"),
        "verifier": ("claude_code", "claude", "deepseek_v4_flash"),
    }
    full_cli = (((profiles.get("modes") or {}).get("full_cli") or {}).get("tiers") or {})
    for tier, tier_config in full_cli.items():
        for role_key, role_config in (tier_config or {}).items():
            role = canonical_role_name(str(role_key))
            binding_role = role
            if not isinstance(role_config, dict):
                matrix_rows.append({
                    "mode": "full_cli",
                    "tier": str(tier),
                    "profile_key": str(role_key),
                    "role": role,
                    "executor_type": str(role_config),
                    "cli_agent": "",
                    "invocation_contract": "",
                    "model_key": "",
                    "model_id": "",
                    "catalog_provider": "",
                    "runtime_provider": "",
                    "model_binding": "",
                    "capacity_route": "",
                    "fallback_routes": "",
                    "fallback_cli_agent": "",
                    "fallback_model_key": "",
                    "artifact_types": "",
                    "artifact_dispatch": "",
                    "artifact_backend": "",
                    "role_binding_status": "not_applicable",
                })
                continue

            cli_agent = str(role_config.get("cli_agent") or "")
            contract_id = str(role_config.get("invocation_contract") or "")
            model_key = str(role_config.get("default") or "")
            capacity_route = str(role_config.get("capacity_route") or "")
            fallback_routes: list[str] = []
            fallback_cli_agents: list[str] = []
            fallback_model_keys: list[str] = []
            model = catalog.get(model_key) or {}
            binding_status = "not_applicable"
            artifact_types = ""
            artifact_dispatch = ""

            if role_config.get("executor_type") == "cli_agent":
                if cli_agent not in workers:
                    errors.append(f"full_cli.{tier}.{role_key}: unknown worker {cli_agent!r}")
                if contract_id not in contracts:
                    errors.append(f"full_cli.{tier}.{role_key}: unknown contract {contract_id!r}")
                elif str((contracts.get(contract_id) or {}).get("worker_id") or "") != cli_agent:
                    errors.append(f"full_cli.{tier}.{role_key}: contract {contract_id!r} belongs to another worker")
                allowed_workers = (roles.get(binding_role) or {}).get("allowed_workers") or []
                binding_status = "ok" if cli_agent in allowed_workers else "mismatch"
                if binding_status != "ok":
                    errors.append(f"full_cli.{tier}.{role_key}: worker {cli_agent!r} is not allowed for {binding_role}")

            if model_key and model_key not in catalog:
                errors.append(f"full_cli.{tier}.{role_key}: unknown model {model_key!r}")
            expected_route = (
                required_performance_routes.get(str(role_key))
                if str(tier) == "performance"
                else None
            )
            actual_route = (cli_agent, contract_id, model_key)
            if expected_route is not None and actual_route != expected_route:
                errors.append(
                    f"full_cli.performance.{role_key}: required default route "
                    f"{expected_route!r}, got {actual_route!r}"
                )
            provider_key = str(model.get("provider") or "")
            provider_command = str(
                ((catalog_providers.get(provider_key) or {}).get("command") or "")
            )
            contract_command = str(
                ((contracts.get(contract_id) or {}).get("command") or "")
            )
            incompatible_cli_surface = (
                cli_agent == "codex" and provider_command != "codex"
            ) or (
                provider_key == "deepseek_official" and cli_agent != "claude_code"
            ) or (
                bool(provider_command)
                and bool(contract_command)
                and provider_command != contract_command
            )
            if incompatible_cli_surface:
                errors.append(
                    f"full_cli.{tier}.{role_key}: model provider {provider_key!r} "
                    f"uses CLI {provider_command or 'none'!r}, not contract command "
                    f"{contract_command or 'none'!r}"
                )

            if binding_role == "ArtifactProducer":
                artifact_types, artifact_dispatch, selected_artifact_rows = (
                    _artifact_dispatch_summary(
                        artifact_policy,
                        tier=str(tier),
                    )
                )
                for artifact_type, provider_config in selected_artifact_rows:
                    provider_worker = str(provider_config.get("worker") or "")
                    provider_contract = str(
                        provider_config.get("invocation_contract") or ""
                    )
                    capacity_tier = {
                        "altered": "alter",
                        "max_quality": "full",
                        "max-quality": "full",
                    }.get(str(tier), str(tier))
                    provider_capacity_route = str(
                        ((provider_config.get("capacity_routes") or {}).get(capacity_tier))
                        or ""
                    )
                    if provider_worker not in workers:
                        errors.append(
                            f"artifact_task_policy.{artifact_type}: unknown worker {provider_worker!r}"
                        )
                    elif provider_worker not in (
                        (roles.get("ArtifactProducer") or {}).get("allowed_workers")
                        or []
                    ):
                        errors.append(
                            f"artifact_task_policy.{artifact_type}: worker {provider_worker!r} "
                            "is not allowed for ArtifactProducer"
                        )
                    if provider_contract not in contracts:
                        errors.append(
                            f"artifact_task_policy.{artifact_type}: unknown contract {provider_contract!r}"
                        )
                    capacity_config = capacity_routes.get(provider_capacity_route)
                    if not isinstance(capacity_config, dict):
                        errors.append(
                            f"artifact_task_policy.{artifact_type}: unknown capacity route "
                            f"{provider_capacity_route!r}"
                        )
                    else:
                        if str(capacity_config.get("worker") or "") != provider_worker:
                            errors.append(
                                f"artifact_task_policy.{artifact_type}: capacity route "
                                f"{provider_capacity_route!r} uses another worker"
                            )
                        if str(
                            capacity_config.get("invocation_contract") or ""
                        ) != provider_contract:
                            errors.append(
                                f"artifact_task_policy.{artifact_type}: capacity route "
                                f"{provider_capacity_route!r} uses another contract"
                            )
                        if canonical_role_name(
                            str(capacity_config.get("role") or "")
                        ) != "ArtifactProducer":
                            errors.append(
                                f"artifact_task_policy.{artifact_type}: capacity route "
                                f"{provider_capacity_route!r} belongs to another role"
                            )

            if capacity_route:
                capacity_cfg = capacity_routes.get(capacity_route)
                if not isinstance(capacity_cfg, dict):
                    errors.append(
                        f"full_cli.{tier}.{role_key}: unknown capacity route {capacity_route!r}"
                    )
                else:
                    route_worker = str(capacity_cfg.get("worker") or "")
                    route_contract = str(capacity_cfg.get("invocation_contract") or "")
                    route_model = str(capacity_cfg.get("model_key") or "")
                    route_role = str(capacity_cfg.get("role") or "")
                    route_pool = str(capacity_cfg.get("pool") or "")
                    if route_worker != cli_agent:
                        errors.append(
                            f"full_cli.{tier}.{role_key}: capacity route {capacity_route!r} "
                            f"uses worker {route_worker!r}, not {cli_agent!r}"
                        )
                    if route_contract != contract_id:
                        errors.append(
                            f"full_cli.{tier}.{role_key}: capacity route {capacity_route!r} "
                            f"uses contract {route_contract!r}, not {contract_id!r}"
                        )
                    if route_model != model_key:
                        errors.append(
                            f"full_cli.{tier}.{role_key}: capacity route {capacity_route!r} "
                            f"uses model {route_model!r}, not {model_key!r}"
                        )
                    if canonical_role_name(route_role) != binding_role:
                        errors.append(
                            f"full_cli.{tier}.{role_key}: capacity route {capacity_route!r} "
                            f"uses role {route_role!r}, not {binding_role!r}"
                        )
                    if route_pool not in capacity_pools:
                        errors.append(
                            f"full_cli.{tier}.{role_key}: capacity route {capacity_route!r} "
                            f"uses unknown pool {route_pool!r}"
                        )

                    for fallback_name in capacity_cfg.get("approved_fallbacks") or []:
                        fallback_route = str(fallback_name)
                        fallback_cfg = capacity_routes.get(fallback_route)
                        if not isinstance(fallback_cfg, dict):
                            errors.append(
                                f"full_cli.{tier}.{role_key}: capacity route {capacity_route!r} "
                                f"references unknown fallback route {fallback_route!r}"
                            )
                            continue
                        fallback_worker = str(fallback_cfg.get("worker") or "")
                        fallback_contract = str(fallback_cfg.get("invocation_contract") or "")
                        fallback_model = str(fallback_cfg.get("model_key") or "")
                        fallback_role = str(fallback_cfg.get("role") or "")
                        fallback_pool = str(fallback_cfg.get("pool") or "")
                        fallback_routes.append(fallback_route)
                        fallback_cli_agents.append(fallback_worker)
                        fallback_model_keys.append(fallback_model)
                        if fallback_worker not in workers:
                            errors.append(
                                f"full_cli.{tier}.{role_key}: fallback route {fallback_route!r} "
                                f"uses unknown worker {fallback_worker!r}"
                            )
                        elif fallback_worker not in ((roles.get(binding_role) or {}).get("allowed_workers") or []):
                            errors.append(
                                f"full_cli.{tier}.{role_key}: fallback route {fallback_route!r} "
                                f"worker {fallback_worker!r} is not allowed for {binding_role}"
                            )
                        if fallback_contract not in contracts:
                            errors.append(
                                f"full_cli.{tier}.{role_key}: fallback route {fallback_route!r} "
                                f"uses unknown contract {fallback_contract!r}"
                            )
                        elif str((contracts.get(fallback_contract) or {}).get("worker_id") or "") != fallback_worker:
                            errors.append(
                                f"full_cli.{tier}.{role_key}: fallback contract {fallback_contract!r} "
                                "belongs to another worker"
                            )
                        if fallback_model not in catalog:
                            errors.append(
                                f"full_cli.{tier}.{role_key}: fallback route {fallback_route!r} "
                                f"uses unknown model {fallback_model!r}"
                            )
                        if fallback_role != route_role:
                            errors.append(
                                f"full_cli.{tier}.{role_key}: fallback route {fallback_route!r} "
                                f"uses role {fallback_role!r}, not {route_role!r}"
                            )
                        if fallback_pool not in capacity_pools:
                            errors.append(
                                f"full_cli.{tier}.{role_key}: fallback route {fallback_route!r} "
                                f"uses unknown pool {fallback_pool!r}"
                            )

            matrix_rows.append({
                "mode": "full_cli",
                "tier": str(tier),
                "profile_key": str(role_key),
                "role": role,
                "executor_type": str(role_config.get("executor_type") or ""),
                "cli_agent": cli_agent,
                "invocation_contract": contract_id,
                "model_key": model_key,
                "model_id": str(model.get("model_id") or ""),
                "catalog_provider": str(model.get("provider") or ""),
                "runtime_provider": _runtime_provider(model),
                "model_binding": str((components.get(cli_agent) or {}).get("model_binding") or "unregistered"),
                "capacity_route": capacity_route,
                "fallback_routes": _join(fallback_routes),
                "fallback_cli_agent": _join(fallback_cli_agents),
                "fallback_model_key": _join(fallback_model_keys),
                "artifact_types": artifact_types,
                "artifact_dispatch": artifact_dispatch,
                "artifact_backend": str(role_config.get("artifact_backend") or ""),
                "role_binding_status": binding_status,
            })

    cli_rows: list[dict[str, str]] = []
    for component_id, component in components.items():
        matching_contracts = [
            name for name, contract in contracts.items()
            if str((contract or {}).get("worker_id") or "") == component_id
        ]
        allowed_roles = [
            role for role, role_cfg in roles.items()
            if component_id in ((role_cfg or {}).get("allowed_workers") or [])
        ]
        cli_rows.append({
            "component": str(component_id),
            "kind": str(component.get("kind") or ""),
            "release_requirement": str(component.get("release_requirement") or ""),
            "command": str(component.get("command") or ""),
            "contracts": _join(matching_contracts),
            "allowed_roles": _join(allowed_roles),
            "auth_mode": str(component.get("auth_mode") or ""),
            "model_binding": str(component.get("model_binding") or ""),
            "install_source": str(component.get("install_source") or ""),
            "version_probe": str(component.get("version_probe") or ""),
            "safe_probe": str(component.get("safe_probe") or ""),
            "live_smoke": str(component.get("live_smoke") or ""),
            "notes": str(component.get("notes") or ""),
        })

    if errors:
        raise ValueError("Invalid AgentLab matrix references:\n- " + "\n- ".join(errors))
    full_cli_authorities = "|".join(
        (
            "config/agent_model_profiles.yml",
            "config/model_catalog.yml",
            "config/model_capacity.yml",
            "config/worker_invocation_contracts.yml",
            "config/agent_role_bindings.yml",
            "config/runtime_cli_requirements.yml",
            "config/artifact_task_policy.yml",
        )
    )
    cli_authorities = "|".join(
        (
            "config/runtime_cli_requirements.yml",
            "config/worker_invocation_contracts.yml",
            "config/agent_role_bindings.yml",
        )
    )
    for row in matrix_rows:
        row["generated_non_authoritative"] = "true"
        row["authority_paths"] = full_cli_authorities
    for row in cli_rows:
        row["generated_non_authoritative"] = "true"
        row["authority_paths"] = cli_authorities
    return matrix_rows, cli_rows


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty matrix: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate(root: Path, full_cli_out: Path, cli_out: Path) -> None:
    matrix_rows, cli_rows = build_matrices(root)
    _write_csv(full_cli_out, matrix_rows)
    _write_csv(cli_out, cli_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--full-cli-out", type=Path)
    parser.add_argument("--cli-out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    generate(
        root,
        (args.full_cli_out or root / "docs" / "AGENTLAB_FULL_CLI_MATRIX.csv").resolve(),
        (args.cli_out or root / "docs" / "AGENTLAB_CLI_REQUIREMENTS.csv").resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
