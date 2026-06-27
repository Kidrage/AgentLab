from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _load_config(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8")) or {}


def test_agent_backend_modes_have_three_canonical_tiers() -> None:
    profiles = _load_config("agent_model_profiles.yml")

    assert profiles["default_mode"] == "full_cli"
    assert set(profiles["tier_policy"]["tiers"]) == {"full", "performance", "low"}

    modes = profiles["modes"]
    for mode_name in ("full_cli", "full_api", "hybrid_ide"):
        assert mode_name in modes
        assert set(modes[mode_name]["tiers"]) == {"full", "performance", "low"}


def test_cli_profiles_reference_worker_invocation_contracts() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]
    runtime_supported_placeholders = {"task_packet_path", "workspace_path"}

    for mode_name, mode in profiles["modes"].items():
        if mode_name == "trusted_headless_cli":
            continue
        for tier_name, tier in mode.get("tiers", {}).items():
            for role_name, role in tier.items():
                if not isinstance(role, dict):
                    continue
                if role.get("executor_type") != "cli_agent":
                    continue

                assert "cli_command" not in role, (
                    f"{mode_name}/{tier_name}/{role_name} duplicates a CLI command; "
                    "use invocation_contract instead"
                )
                contract_name = role.get("invocation_contract")
                assert contract_name in contracts, (
                    f"{mode_name}/{tier_name}/{role_name} references missing "
                    f"invocation contract {contract_name!r}"
                )
                contract = contracts[contract_name]
                required_placeholders = set(contract.get("required_placeholders") or [])
                template_placeholders = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", contract.get("template") or ""))
                assert required_placeholders <= runtime_supported_placeholders, (
                    f"{mode_name}/{tier_name}/{role_name} references "
                    f"{contract_name!r}, which requires unsupported placeholders "
                    f"{sorted(required_placeholders - runtime_supported_placeholders)}"
                )
                assert template_placeholders <= runtime_supported_placeholders, (
                    f"{mode_name}/{tier_name}/{role_name} references "
                    f"{contract_name!r}, whose template has unsupported placeholders "
                    f"{sorted(template_placeholders - runtime_supported_placeholders)}"
                )


def test_driver_modes_map_to_agent_backend_modes_without_role_defaults() -> None:
    execution_modes = _load_config("execution_modes.yml")
    backend_modes = set(_load_config("agent_model_profiles.yml")["modes"])

    assert execution_modes["authority"]["purpose"] == "driver_mode_selection"

    for mode_name, mode in execution_modes["execution_modes"].items():
        assert "agent_backend_mode" in mode
        backend = mode["agent_backend_mode"]
        assert backend in backend_modes or backend == "external_driver", mode_name

        serialized = yaml.safe_dump(mode)
        forbidden_role_keys = (
            "supervisor:",
            "reposcout:",
            "coder:",
            "tester_auditor:",
            "archivist:",
        )
        assert not any(key in serialized for key in forbidden_role_keys)


def test_advisory_worker_policy_cannot_override_agent_backends() -> None:
    policy = _load_config("mode_tier_worker_policy.yml")
    authority = policy["authority"]

    assert authority["purpose"] == "advisory_worker_preferences"
    assert authority["runtime_decision_source"] == "config/agent_model_profiles.yml"
    assert authority["may_override_agent_backend"] is False


def test_external_executor_router_is_not_agent_backend_source() -> None:
    router = _load_config("executor_router.yml")["executor_router"]
    authority = router["authority"]

    assert authority["purpose"] == "task_level_external_executor_routing"
    assert authority["runtime_agent_backend_source"] == "config/agent_model_profiles.yml"
    assert authority["may_override_agent_backend"] is False


def test_config_directory_has_no_tracked_backup_configs() -> None:
    backup_configs = sorted((ROOT / "config").glob("*.bak"))
    assert backup_configs == []
