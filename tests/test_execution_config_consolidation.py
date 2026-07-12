from __future__ import annotations

import re
from pathlib import Path

import yaml

from agent_runtime.cli.models import _cost_source


ROOT = Path(__file__).resolve().parents[1]


def _load_config(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8")) or {}


def test_agent_backend_modes_have_three_canonical_tiers() -> None:
    profiles = _load_config("agent_model_profiles.yml")

    assert profiles["default_mode"] == "full_cli"
    assert set(profiles["tier_policy"]["tiers"]) == {"full", "performance", "low"}

    modes = profiles["modes"]
    for mode_name in ("full_cli", "qwen_token_plan_cli", "full_api", "hybrid_ide"):
        assert mode_name in modes
        assert set(modes[mode_name]["tiers"]) == {"full", "performance", "low"}


def test_cli_profiles_reference_worker_invocation_contracts() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]
    runtime_supported_placeholders = {
        "task_packet_path",
        "workspace_path",
        "provider",
        "model_id",
        "model_key",
    }

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


def test_cli_profiles_invocation_contracts_match_selected_workers() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]

    for mode_name, mode in profiles["modes"].items():
        if mode_name == "trusted_headless_cli":
            continue
        for tier_name, tier in mode.get("tiers", {}).items():
            for role_name, role in tier.items():
                if not isinstance(role, dict) or role.get("executor_type") != "cli_agent":
                    continue

                cli_agent = role.get("cli_agent")
                contract_name = role.get("invocation_contract")
                contract_worker = contracts[contract_name]["worker_id"]
                assert contract_worker == cli_agent, (
                    f"{mode_name}/{tier_name}/{role_name} selects cli_agent "
                    f"{cli_agent!r} but invocation_contract {contract_name!r} "
                    f"runs worker {contract_worker!r}"
                )

                fallback_cli_agent = role.get("fallback_cli_agent")
                fallback_contract_name = role.get("fallback_invocation_contract")
                if fallback_cli_agent:
                    assert fallback_contract_name in contracts, (
                        f"{mode_name}/{tier_name}/{role_name} selects fallback_cli_agent "
                        f"{fallback_cli_agent!r} without a valid fallback_invocation_contract"
                    )
                    fallback_contract_worker = contracts[fallback_contract_name]["worker_id"]
                    assert fallback_contract_worker == fallback_cli_agent, (
                        f"{mode_name}/{tier_name}/{role_name} selects fallback_cli_agent "
                        f"{fallback_cli_agent!r} but fallback_invocation_contract "
                        f"{fallback_contract_name!r} runs worker {fallback_contract_worker!r}"
                    )


def test_agent_model_profiles_reference_existing_artifact_backends() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    media_backends = _load_config("media_generation_backends.yml")["backends"]
    valid_backend_ids = set(media_backends)

    for mode_name, mode in profiles["modes"].items():
        for tier_name, tier in mode.get("tiers", {}).items():
            for role_name, role in tier.items():
                if not isinstance(role, dict):
                    continue
                for key in ("artifact_backend", "fallback_artifact_backend"):
                    backend_id = role.get(key)
                    if backend_id:
                        assert backend_id in valid_backend_ids, (
                            f"{mode_name}/{tier_name}/{role_name} references missing "
                            f"{key} {backend_id!r}"
                        )


def test_full_cli_performance_defaults_match_role_policy() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    tier = profiles["modes"]["full_cli"]["tiers"]["performance"]

    assert tier["supervisor"]["cli_agent"] == "hermes"
    assert tier["supervisor"]["invocation_contract"] == "hermes"
    assert tier["supervisor"]["default"] == "codex_gpt_5_5_high_hermes_oauth"
    assert tier["supervisor"]["fallback_cli_agent"] == "claude_code"
    assert tier["supervisor"]["fallback_invocation_contract"] == "claude"
    assert tier["supervisor"]["fallback"] == "deepseek_v4_pro"

    assert tier["reposcout"]["cli_agent"] == "codex"
    assert tier["reposcout"]["default"] == "deepseek_v4_pro"

    assert tier["interface_mapper"]["cli_agent"] == "codex"
    assert tier["interface_mapper"]["default"] == "deepseek_v4_pro"
    assert tier["interface_mapper"]["fallback"] == "qwen3_6_plus_dashscope"

    assert tier["researcher"]["cli_agent"] == "qwen"
    assert tier["researcher"]["default"] == "deepseek_v4_flash"
    assert tier["researcher"]["fallback_cli_agent"] == "claude_code"
    assert tier["researcher"]["fallback"] == "deepseek_v4_flash"

    assert tier["prompt_engineer"]["cli_agent"] == "hermes"
    assert tier["prompt_engineer"]["default"] == "deepseek_v4_flash"
    assert tier["prompt_engineer"]["fallback_cli_agent"] == "hermes"
    assert tier["prompt_engineer"]["fallback"] == "deepseek_v4_pro"

    assert tier["coder"]["cli_agent"] == "claude_code"
    assert tier["coder"]["default"] == "qwen3_coder_plus_dashscope"
    assert tier["coder"]["fallback_cli_agent"] == "codex"

    assert tier["artifact_producer"]["cli_agent"] == "agy"
    assert tier["artifact_producer"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["artifact_producer"]["artifact_backend"] == "hermes_grok_oauth"
    assert tier["artifact_producer"]["fallback_cli_agent"] == "agy"
    assert tier["artifact_producer"]["fallback_artifact_backend"] == "agy_media"

    assert tier["tester_auditor"]["cli_agent"] == "codex"
    assert tier["tester_auditor"]["default"] == "deepseek_v4_pro"

    assert tier["verifier"]["cli_agent"] == "codex"
    assert tier["verifier"]["fallback_cli_agent"] == "claude_code"
    assert tier["verifier"]["default"] == "deepseek_v4_flash"

    assert tier["archivist"]["cli_agent"] == "claude_code"
    assert tier["archivist"]["default"] == "deepseek_v4_pro"
    assert tier["archivist"]["fallback"] == "qwen3_6_flash_dashscope"

    assert tier["writer"]["cli_agent"] == "agy"
    assert tier["writer"]["invocation_contract"] == "agy_writer"
    assert tier["writer"]["fallback_cli_agent"] == "claude_code"
    assert tier["writer"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["writer"]["fallback"] == "deepseek_v4_flash"


def test_full_cli_full_tier_matches_operator_matrix() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    tier = profiles["modes"]["full_cli"]["tiers"]["full"]

    assert tier["supervisor"]["cli_agent"] == "hermes"
    assert tier["supervisor"]["invocation_contract"] == "hermes"
    assert tier["supervisor"]["default"] == "codex_gpt_5_5_high_hermes_oauth"
    assert tier["supervisor"]["fallback_cli_agent"] == "claude_code"
    assert tier["supervisor"]["fallback_invocation_contract"] == "claude"
    assert tier["supervisor"]["fallback"] == "deepseek_v4_pro"

    assert tier["reposcout"]["cli_agent"] == "agy"
    assert tier["reposcout"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["reposcout"]["fallback_cli_agent"] == "claude_code"
    assert tier["reposcout"]["fallback"] == "deepseek_v4_pro"

    assert tier["interface_mapper"]["cli_agent"] == "agy"
    assert tier["interface_mapper"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["interface_mapper"]["fallback_cli_agent"] == "claude_code"
    assert tier["interface_mapper"]["fallback"] == "deepseek_v4_pro"

    assert tier["researcher"]["cli_agent"] == "claude_code"
    assert tier["researcher"]["default"] == "deepseek_v4_flash"
    assert tier["researcher"]["fallback_cli_agent"] == "hermes"
    assert tier["researcher"]["fallback"] == "qwen3_coder_next_dashscope"

    assert tier["prompt_engineer"]["cli_agent"] == "hermes"
    assert tier["prompt_engineer"]["default"] == "qwen3_7_max_dashscope"
    assert tier["prompt_engineer"]["fallback_cli_agent"] == "claude_code"
    assert tier["prompt_engineer"]["fallback"] == "deepseek_v4_pro"

    assert tier["coder"]["cli_agent"] == "claude_code"
    assert tier["coder"]["default"] == "deepseek_v4_pro"
    assert tier["coder"]["fallback_cli_agent"] == "hermes"
    assert tier["coder"]["fallback"] == "qwen3_7_max_dashscope"

    assert tier["tester_auditor"]["cli_agent"] == "hermes"
    assert tier["tester_auditor"]["default"] == "qwen3_7_max_dashscope"
    assert tier["tester_auditor"]["fallback_cli_agent"] == "claude_code"
    assert tier["tester_auditor"]["fallback"] == "deepseek_v4_pro"

    assert tier["verifier"]["cli_agent"] == "hermes"
    assert tier["verifier"]["default"] == "qwen3_6_flash_dashscope"
    assert tier["verifier"]["fallback_cli_agent"] == "claude_code"
    assert tier["verifier"]["fallback"] == "deepseek_v4_flash"

    assert tier["archivist"]["cli_agent"] == "agy"
    assert tier["archivist"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["archivist"]["fallback_cli_agent"] == "hermes"
    assert tier["archivist"]["fallback"] == "qwen3_7_max_dashscope"

    assert tier["writer"]["cli_agent"] == "agy"
    assert tier["writer"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["writer"]["fallback_cli_agent"] == "claude_code"
    assert tier["writer"]["fallback"] == "deepseek_v4_flash"


def test_qwen_token_plan_cli_preserves_original_cli_allocation() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    tier = profiles["modes"]["qwen_token_plan_cli"]["tiers"]["performance"]

    assert tier["supervisor"]["cli_agent"] == "hermes"
    assert tier["supervisor"]["default"] == "deepseek_v4_pro"
    assert tier["reposcout"]["cli_agent"] == "codex"
    assert tier["reposcout"]["default"] == "qwen3_6_plus_tokenplan"
    assert tier["interface_mapper"]["cli_agent"] == "codex"
    assert tier["interface_mapper"]["default"] == "qwen3_6_plus_tokenplan"
    assert tier["prompt_engineer"]["cli_agent"] == "hermes"
    assert tier["prompt_engineer"]["default"] == "qwen3_6_plus_tokenplan"
    assert tier["coder"]["cli_agent"] == "claude_code"
    assert tier["coder"]["default"] == "qwen3_coder_plus_tokenplan"
    assert tier["artifact_producer"]["cli_agent"] == "codex"
    assert tier["artifact_producer"]["default"] == "qwen3_6_plus_tokenplan"
    assert tier["tester_auditor"]["cli_agent"] == "codex"
    assert tier["tester_auditor"]["default"] == "qwen3_6_plus_tokenplan"
    assert tier["verifier"]["cli_agent"] == "codex"
    assert tier["verifier"]["default"] == "qwen3_6_flash_tokenplan"
    assert tier["archivist"]["cli_agent"] == "claude_code"
    assert tier["archivist"]["default"] == "qwen3_6_plus_tokenplan"
    assert tier["writer"]["executor_type"] == "direct_api"
    assert tier["writer"]["default"] == "deepseek_v4_flash"
    assert tier["writer"]["fallback"] == "qwen3_6_plus_tokenplan"


def test_qwen_token_plan_models_route_to_tokenplan_provider() -> None:
    catalog = _load_config("model_catalog.yml")
    providers = _load_config("model_providers.yml")["providers"]

    tokenplan_keys = [
        "qwen3_7_max_tokenplan",
        "qwen3_6_plus_tokenplan",
        "qwen3_6_flash_tokenplan",
        "qwen3_coder_next_tokenplan",
        "qwen3_coder_plus_tokenplan",
    ]
    for key in tokenplan_keys:
        model = catalog["models"][key]
        assert model["provider"] == "qwen_token_plan"
        assert model["runtime_provider"] == "tokenplan-qwen"

    provider = providers["tokenplan-qwen"]
    assert provider["api_key"] == "env:QWEN_TOKEN_PLAN_API_KEY"
    assert provider["base_url"] == "env:QWEN_TOKEN_PLAN_BASE_URL"


def test_agy_is_default_gemini_oauth_path_and_api_gemini_is_explicit_fallback() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    catalog = _load_config("model_catalog.yml")
    providers = _load_config("model_providers.yml")["providers"]
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]

    tier = profiles["modes"]["full_cli"]["tiers"]["performance"]
    assert profiles["default_mode"] == "full_cli"
    assert tier["writer"]["cli_agent"] == "agy"
    assert tier["writer"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["artifact_producer"]["cli_agent"] == "agy"
    assert tier["artifact_producer"]["default"] == "gemini_3_5_flash_high_agy_oauth"

    agy_model = catalog["models"]["gemini_3_5_flash_high_agy_oauth"]
    assert agy_model["runtime_provider"] == "agy-gemini-oauth"
    assert agy_model["model_id"] == "gemini-3.5-flash-high"
    assert agy_model["cli_model_id"] == "Gemini 3.5 Flash (High)"
    assert agy_model["pricing"]["billing_source"] == "agy_oauth"

    api_model = catalog["models"]["gemini_2_5_flash_high_api"]
    assert api_model["runtime_provider"] == "gemini-api"
    assert api_model["usage_policy"]["never_default"] is True

    assert providers["agy-gemini-oauth"]["type"] == "oauth_cli"
    assert providers["agy-gemini-oauth"]["default_model"] == "gemini-3.5-flash-high"
    assert catalog["providers"]["agy_gemini_oauth"]["cli_model_id"] == "Gemini 3.5 Flash (High)"
    assert providers["gemini-api"]["never_default"] is True
    assert providers["gemini-api"]["api_key"] == "env:GEMINI_API_KEY"
    assert "Do not use GEMINI_API_KEY" in contracts["agy_coder"]["template"]
    assert '--model "{model_id}"' in contracts["agy_coder"]["template"]
    assert "Read only the sealed AgentLab Writer packet" in contracts["agy_writer"]["template"]
    assert "do not read any other" in contracts["agy_writer"]["template"]
    assert '--model "{model_id}"' in contracts["agy_writer"]["template"]
    assert _cost_source(agy_model, {}) == "oauth/subscription quota"
    assert _cost_source(api_model, {}) == "free-tier/api quota"


def test_codex_gpt_55_high_is_registered_as_hermes_oauth_provider() -> None:
    catalog = _load_config("model_catalog.yml")
    providers = _load_config("model_providers.yml")["providers"]
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]

    model = catalog["models"]["codex_gpt_5_5_high_hermes_oauth"]
    assert model["provider"] == "hermes_codex_oauth"
    assert model["provider"] in catalog["providers"]
    assert model["runtime_provider"] == "openai-codex"
    assert model["runtime_provider"] in providers
    assert model["cli_provider"] == "openai-codex"
    assert model["model_id"] == "gpt-5.5"
    assert model["reasoning_effort"] == "high"
    assert _cost_source(model, {}) == "oauth/subscription quota"

    provider = providers["openai-codex"]
    assert provider["type"] == "oauth_cli"
    assert provider["command"] == "hermes"
    assert provider["default_model"] == "gpt-5.5"
    assert provider["reasoning_effort"] == "high"

    hermes_template = contracts["hermes"]["template"]
    assert "--provider {provider}" in hermes_template
    assert "-m {model_id}" in hermes_template


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
