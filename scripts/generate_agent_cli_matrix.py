#!/usr/bin/env python3
"""Generate copyable CSV views from AgentLab's authoritative YAML registries."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import yaml


ROLE_NAMES = {
    "supervisor": "Supervisor",
    "reposcout": "RepoScout",
    "researcher": "Researcher",
    "interface_mapper": "InterfaceMapper",
    "prompt_engineer": "PromptEngineer",
    "coder": "Coder",
    "artifact_producer": "ArtifactProducer",
    "writer": "Writer",
    "reviewer": "Reviewer",
    "scribe": "Scribe",
    "tester_auditor": "TesterAuditor",
    "verifier": "Verifier",
    "archivist": "Archivist",
}


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


def build_matrices(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    config = root / "config"
    profiles = _read_yaml(config / "agent_model_profiles.yml")
    catalog = (_read_yaml(config / "model_catalog.yml").get("models") or {})
    contracts = (_read_yaml(config / "worker_invocation_contracts.yml").get("contracts") or {})
    bindings = _read_yaml(config / "agent_role_bindings.yml")
    requirements = _read_yaml(config / "runtime_cli_requirements.yml")
    workers = bindings.get("workers") or {}
    roles = bindings.get("roles") or {}
    components = requirements.get("components") or {}

    errors: list[str] = []
    matrix_rows: list[dict[str, str]] = []
    full_cli = (((profiles.get("modes") or {}).get("full_cli") or {}).get("tiers") or {})
    for tier, tier_config in full_cli.items():
        for role_key, role_config in (tier_config or {}).items():
            role = ROLE_NAMES.get(str(role_key), str(role_key))
            if not isinstance(role_config, dict):
                matrix_rows.append({
                    "mode": "full_cli",
                    "tier": str(tier),
                    "role": role,
                    "executor_type": str(role_config),
                    "cli_agent": "",
                    "invocation_contract": "",
                    "model_key": "",
                    "model_id": "",
                    "catalog_provider": "",
                    "runtime_provider": "",
                    "model_binding": "",
                    "fallback_cli_agent": "",
                    "fallback_model_key": "",
                    "artifact_backend": "",
                    "role_binding_status": "not_applicable",
                })
                continue

            cli_agent = str(role_config.get("cli_agent") or "")
            contract_id = str(role_config.get("invocation_contract") or "")
            model_key = str(role_config.get("default") or "")
            fallback_model = str(role_config.get("fallback") or "")
            model = catalog.get(model_key) or {}
            binding_status = "not_applicable"

            if role_config.get("executor_type") == "cli_agent":
                if cli_agent not in workers:
                    errors.append(f"full_cli.{tier}.{role_key}: unknown worker {cli_agent!r}")
                if contract_id not in contracts:
                    errors.append(f"full_cli.{tier}.{role_key}: unknown contract {contract_id!r}")
                elif str((contracts.get(contract_id) or {}).get("worker_id") or "") != cli_agent:
                    errors.append(f"full_cli.{tier}.{role_key}: contract {contract_id!r} belongs to another worker")
                allowed_workers = (roles.get(role) or {}).get("allowed_workers") or []
                binding_status = "ok" if cli_agent in allowed_workers else "mismatch"
                if binding_status != "ok":
                    errors.append(f"full_cli.{tier}.{role_key}: worker {cli_agent!r} is not allowed for {role}")

            if model_key and model_key not in catalog:
                errors.append(f"full_cli.{tier}.{role_key}: unknown model {model_key!r}")
            if fallback_model and fallback_model not in catalog:
                errors.append(f"full_cli.{tier}.{role_key}: unknown fallback model {fallback_model!r}")

            matrix_rows.append({
                "mode": "full_cli",
                "tier": str(tier),
                "role": role,
                "executor_type": str(role_config.get("executor_type") or ""),
                "cli_agent": cli_agent,
                "invocation_contract": contract_id,
                "model_key": model_key,
                "model_id": str(model.get("model_id") or ""),
                "catalog_provider": str(model.get("provider") or ""),
                "runtime_provider": _runtime_provider(model),
                "model_binding": str((components.get(cli_agent) or {}).get("model_binding") or "unregistered"),
                "fallback_cli_agent": str(role_config.get("fallback_cli_agent") or ""),
                "fallback_model_key": fallback_model,
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
