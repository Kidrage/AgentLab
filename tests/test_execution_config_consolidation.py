from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml

from agent_runtime.cli.models import _cost_source
from agent_runtime.role_keys import canonical_role_name


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


def test_agent_registry_contains_only_role_contracts() -> None:
    registry = _load_config("agent_registry.yml")
    authority = registry["authority"]
    assert authority["purpose"] == "canonical_agent_role_contracts"
    assert authority["backend_source"] == "config/agent_model_profiles.yml"

    forbidden = {
        "model_profile",
        "model_tier",
        "profile_mapping",
        "execution_owner",
        "secondary_executor",
        "local_executor",
        "allowed_backends",
        "invocation_contract",
        "external_window",
        "external_window_activation",
    }
    for role_name, role in registry["agents"].items():
        assert forbidden.isdisjoint(role), (
            f"{role_name} duplicates backend/model authority in agent_registry.yml"
        )


def test_execution_policy_does_not_duplicate_backend_or_model_selection() -> None:
    policy = _load_config("execution_policy.yml")
    authority = policy["authority"]

    assert authority["purpose"] == "execution_gates_and_budget_behavior"
    assert authority["role_backend_source"] == "config/agent_model_profiles.yml"
    assert authority["fallback_source"] == "config/model_capacity.yml"
    assert "default_api_coder" not in policy["execution_policy"]
    assert "cross_family_review" not in policy["audit_policy"]


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


def test_generic_claude_coder_contract_isolates_project_customizations() -> None:
    contract = _load_config("worker_invocation_contracts.yml")["contracts"]["claude"]
    argv = shlex.split(contract["template"].format(
        task_packet_path="/tmp/task_packet.yml",
        model_id="deepseek-v4-pro",
    ))

    assert "--safe-mode" in argv
    assert "--no-session-persistence" in argv


def test_profile_role_keys_resolve_to_registered_roles() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    registered_roles = set(_load_config("agent_role_bindings.yml")["roles"])

    for mode_name, mode in profiles["modes"].items():
        for tier_name, tier in mode.get("tiers", {}).items():
            for role_key in tier:
                canonical = canonical_role_name(str(role_key))
                assert canonical in registered_roles, (
                    f"{mode_name}/{tier_name}/{role_key} does not resolve to a "
                    "registered AgentLab role"
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


def test_agent_model_profiles_delegate_all_automatic_fallbacks_to_capacity_policy() -> None:
    profiles = _load_config("agent_model_profiles.yml")

    authority = profiles["authority"]
    assert authority["automatic_fallback_source"] == "config/model_capacity.yml"
    assert authority["undeclared_failure_policy"] == "stop_and_report"

    forbidden_route_fields = {
        "fallback",
        "fallback_cli_agent",
        "fallback_invocation_contract",
        "fallback_artifact_backend",
    }
    for mode_name, mode in profiles["modes"].items():
        for tier_name, tier in mode.get("tiers", {}).items():
            for role_name, role in tier.items():
                if not isinstance(role, dict):
                    continue
                assert forbidden_route_fields.isdisjoint(role), (
                    f"{mode_name}/{tier_name}/{role_name} declares a profile-level "
                    "fallback; executable fallback routes belong only in "
                    "config/model_capacity.yml"
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

    assert tier["supervisor"]["cli_agent"] == "codex"
    assert tier["supervisor"]["invocation_contract"] == "codex_supervisor"
    assert tier["supervisor"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"
    assert tier["supervisor"]["capacity_route"] == "Supervisor"
    assert tier["observer"]["cli_agent"] == "agy"
    assert tier["observer"]["invocation_contract"] == "agy_observer"

    assert tier["reposcout"]["cli_agent"] == "codex"
    assert tier["reposcout"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"

    assert tier["interface_mapper"]["cli_agent"] == "codex"
    assert tier["interface_mapper"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"

    assert tier["researcher"]["cli_agent"] == "grok"
    assert tier["researcher"]["invocation_contract"] == "grok_research"
    assert tier["researcher"]["default"] == "grok_4_3_hermes_oauth"

    assert tier["prompt_engineer"]["cli_agent"] == "claude_code"
    assert tier["prompt_engineer"]["invocation_contract"] == "claude"
    assert tier["prompt_engineer"]["default"] == "deepseek_v4_flash"

    assert tier["coder"]["cli_agent"] == "claude_code"
    assert tier["coder"]["default"] == "deepseek_v4_pro"

    assert tier["artifact_producer"]["cli_agent"] == "grok"
    assert tier["artifact_producer"]["invocation_contract"] == "grok_media"
    assert tier["artifact_producer"]["default"] == "grok_4_3_hermes_oauth"
    assert tier["artifact_producer"]["artifact_backend"] == "hermes_grok_oauth"

    assert tier["narrative_planner"]["cli_agent"] == "claude_code"
    assert tier["narrative_planner"]["invocation_contract"] == "claude_narrative_planner"
    assert tier["narrative_planner"]["default"] == "deepseek_v4_pro"
    assert tier["narrative_planner"]["capacity_route"] == "NarrativePlannerRewrite"

    assert tier["tester_auditor"]["cli_agent"] == "codex"
    assert tier["tester_auditor"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"

    assert tier["verifier"]["cli_agent"] == "codex"
    assert tier["verifier"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"

    assert tier["archivist"]["cli_agent"] == "claude_code"
    assert tier["archivist"]["default"] == "deepseek_v4_pro"

    assert tier["writer"]["cli_agent"] == "claude_code"
    assert tier["writer"]["invocation_contract"] == "claude_writer"
    assert tier["writer"]["default"] == "deepseek_v4_pro"
    assert tier["writer"]["capacity_route"] == "Writer"


def test_full_cli_full_tier_matches_operator_matrix() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    tier = profiles["modes"]["full_cli"]["tiers"]["full"]

    assert tier["supervisor"]["cli_agent"] == "codex"
    assert tier["supervisor"]["invocation_contract"] == "codex_supervisor"
    assert tier["supervisor"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"
    assert tier["observer"]["invocation_contract"] == "agy_observer"

    assert tier["reposcout"]["cli_agent"] == "codex"
    assert tier["reposcout"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"

    assert tier["interface_mapper"]["cli_agent"] == "codex"
    assert tier["interface_mapper"]["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"

    assert tier["researcher"]["cli_agent"] == "grok"
    assert tier["researcher"]["invocation_contract"] == "grok_research"
    assert tier["researcher"]["default"] == "grok_4_3_hermes_oauth"

    assert tier["prompt_engineer"]["cli_agent"] == "hermes"
    assert tier["prompt_engineer"]["default"] == "qwen3_7_max_dashscope"

    assert tier["coder"]["cli_agent"] == "claude_code"
    assert tier["coder"]["default"] == "deepseek_v4_pro"

    assert tier["tester_auditor"]["cli_agent"] == "hermes"
    assert tier["tester_auditor"]["default"] == "qwen3_7_max_dashscope"

    assert tier["verifier"]["cli_agent"] == "hermes"
    assert tier["verifier"]["default"] == "qwen3_6_flash_dashscope"

    assert tier["archivist"]["cli_agent"] == "claude_code"
    assert tier["archivist"]["default"] == "deepseek_v4_pro"

    assert tier["artifact_producer"]["cli_agent"] == "grok"
    assert tier["artifact_producer"]["invocation_contract"] == "grok_media"
    assert tier["narrative_planner"]["cli_agent"] == "claude_code"
    assert tier["narrative_planner"]["default"] == "deepseek_v4_pro"
    assert tier["narrative_planner"]["capacity_route"] == "NarrativePlannerRewrite"
    assert tier["writer"]["cli_agent"] == "claude_code"
    assert tier["writer"]["invocation_contract"] == "claude_writer"
    assert tier["writer"]["default"] == "deepseek_v4_pro"
    assert tier["writer"]["capacity_route"] == "Writer"


def test_narrative_planner_capacity_route_has_no_fallback() -> None:
    capacity = _load_config("model_capacity.yml")["routes"]
    route = capacity["NarrativePlannerRewrite"]
    contract = _load_config("worker_invocation_contracts.yml")["contracts"][
        "claude_narrative_planner"
    ]

    assert route == {
        "role": "narrative_planner",
        "worker": "claude_code",
        "invocation_contract": "claude_narrative_planner",
        "model_key": "deepseek_v4_pro",
        "pool": "deepseek_metered_api",
        "approved_fallbacks": [],
        "fallback_on": [],
        "activation_policy": "blocking_narrative_rewrite_only",
    }
    assert contract["worker_id"] == "claude_code"
    assert contract["fallback"] == {
        "on_binary_missing": "stop_and_report",
        "on_quota_exhausted": "stop_and_report",
    }


def test_narrative_planner_is_fixed_to_pro_in_every_full_cli_tier() -> None:
    tiers = _load_config("agent_model_profiles.yml")["modes"]["full_cli"]["tiers"]
    for tier_name in ("full", "performance", "low"):
        planner = tiers[tier_name]["narrative_planner"]
        assert planner["executor_type"] == "cli_agent"
        assert planner["cli_agent"] == "claude_code"
        assert planner["invocation_contract"] == "claude_narrative_planner"
        assert planner["default"] == "deepseek_v4_pro"
        assert planner["capacity_route"] == "NarrativePlannerRewrite"


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


def test_agy_is_multimodal_observer_and_not_writer_or_image_renderer() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    catalog = _load_config("model_catalog.yml")
    providers = _load_config("model_providers.yml")["providers"]
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]
    bindings = _load_config("agent_role_bindings.yml")

    tier = profiles["modes"]["full_cli"]["tiers"]["performance"]
    assert profiles["default_mode"] == "full_cli"
    assert tier["observer"]["cli_agent"] == "agy"
    assert tier["observer"]["invocation_contract"] == "agy_observer"
    assert tier["observer"]["default"] == "gemini_3_5_flash_high_agy_oauth"
    assert tier["writer"]["cli_agent"] == "claude_code"
    assert tier["artifact_producer"]["cli_agent"] == "grok"
    assert "Writer" not in bindings["workers"]["agy"]["allowed_roles"]
    assert "Observer" in bindings["workers"]["agy"]["allowed_roles"]

    agy_model = catalog["models"]["gemini_3_5_flash_high_agy_oauth"]
    assert agy_model["runtime_provider"] == "agy-gemini-oauth"
    assert agy_model["model_id"] == "gemini-3.5-flash-high"
    assert agy_model["cli_model_id"] == "Gemini 3.5 Flash (High)"
    assert agy_model["pricing"]["billing_source"] == "agy_oauth"
    assert agy_model["capabilities"]["input_modalities"] == [
        "text", "image", "video", "audio", "pdf"
    ]
    assert agy_model["capabilities"]["output_modalities"] == ["text"]
    assert agy_model["capabilities"]["image_generation"] is False

    api_model = catalog["models"]["gemini_2_5_flash_high_api"]
    assert api_model["runtime_provider"] == "gemini-api"
    assert api_model["usage_policy"]["never_default"] is True

    assert providers["agy-gemini-oauth"]["type"] == "oauth_cli"
    assert providers["agy-gemini-oauth"]["default_model"] == "gemini-3.5-flash-high"
    assert catalog["providers"]["agy_gemini_oauth"]["cli_model_id"] == "Gemini 3.5 Flash (High)"
    assert providers["gemini-api"]["never_default"] is True
    assert providers["gemini-api"]["api_key"] == "env:GEMINI_API_KEY"
    assert "Do not use GEMINI_API_KEY" in contracts["agy_observer"]["template"]
    assert '--model "{model_id}"' in contracts["agy_observer"]["template"]
    assert "read-only multimodal Observer" in contracts["agy_observer"]["template"]
    assert "agy_writer" not in contracts
    assert _cost_source(agy_model, {}) == "oauth/subscription quota"
    assert _cost_source(api_model, {}) == "free-tier/api quota"


def test_agy_observer_models_use_independent_honest_capacity_pools() -> None:
    catalog = _load_config("model_catalog.yml")
    providers = _load_config("model_providers.yml")["providers"]
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]
    capacity = _load_config("model_capacity.yml")

    model = catalog["models"]["claude_sonnet_4_6_agy_oauth"]
    assert model["provider"] == "agy_claude_oauth"
    assert model["runtime_provider"] == "agy-claude-oauth"
    assert model["cli_model_id"] == "Claude Sonnet 4.6 (Thinking)"
    assert model["usage_policy"]["never_primary"] is True
    assert model["usage_policy"]["perception_fallback_only"] is True
    assert model["usage_policy"]["allowed_failure_classes"] == [
        "quota_exhausted",
        "rate_limited",
        "model_unavailable",
    ]
    assert model["capacity_pool"] == "agy_claude_observer"
    assert catalog["models"]["gemini_3_5_flash_high_agy_oauth"]["capacity_pool"] == "agy_gemini_observer"

    provider = providers["agy-claude-oauth"]
    assert provider["type"] == "oauth_cli"
    assert provider["command"] == "agy"
    assert provider["default_model"] == "Claude Sonnet 4.6 (Thinking)"
    assert provider["never_primary"] is True
    assert "api_key" not in provider

    pools = capacity["pools"]
    assert pools["agy_gemini_observer"]["shared_pool_id"] != pools["agy_claude_observer"]["shared_pool_id"]
    for pool_id in ("agy_gemini_observer", "agy_claude_observer"):
        assert pools[pool_id]["declared_windows"]["rolling"]["period_seconds"] == 18_000
        assert pools[pool_id]["declared_windows"]["rolling"]["remaining"] is None
        assert pools[pool_id]["declared_windows"]["rolling"]["reset_at"] is None
        assert pools[pool_id]["declared_windows"]["weekly"]["remaining"] is None
    primary = capacity["routes"]["Observer"]
    fallback = capacity["routes"][primary["approved_fallbacks"][0]]
    assert primary["pool"] == "agy_gemini_observer"
    assert fallback["pool"] == "agy_claude_observer"
    assert primary["fallback_on"] == model["usage_policy"][
        "allowed_failure_classes"
    ]
    assert contracts["agy_observer"]["worker_id"] == "agy"


def test_writer_light_contract_has_one_unambiguous_four_file_response() -> None:
    registry = _load_config("agent_registry.yml")
    writer = registry["agents"]["Writer"]
    expected = [
        "runs/task_xxxx/fiction_draft.md",
        "runs/task_xxxx/continuity_ledger.yml",
        "runs/task_xxxx/state_transition_proposal.yml",
        "runs/task_xxxx/narrative_delivery_receipt.yml",
    ]
    assert writer["required_outputs"] == expected

    root = Path(__file__).resolve().parents[1]
    template = (root / "agent_templates" / "writer.md").read_text(encoding="utf-8")
    skill = (
        root / "skills" / "active" / "skill_agentlab_narrative_chapter_writer_lite" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "exactly those\nfour closed blocks" in template
    assert "exactly these four closed `AGENTLAB_EDIT`" in skill
    assert "no preamble" in skill


def test_codex_supervisor_uses_native_gpt_56_sol_at_xhigh_effort() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    catalog = _load_config("model_catalog.yml")
    providers = _load_config("model_providers.yml")["providers"]
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]

    model = catalog["models"]["codex_gpt_5_6_sol_xhigh_cli_oauth"]
    assert model["provider"] == "codex_cli_oauth"
    assert model["provider"] in catalog["providers"]
    assert model["runtime_provider"] == "codex-cli"
    assert model["runtime_provider"] in providers
    assert model["cli_provider"] == "codex"
    assert model["model_id"] == "gpt-5.6-sol"
    assert model["reasoning_effort"] == "xhigh"
    assert model["reasoning_effort_label"] == "extra"
    assert _cost_source(model, {}) == "oauth/subscription quota"

    provider = providers["codex-cli"]
    assert provider["type"] == "oauth_cli"
    assert provider["command"] == "codex"
    assert provider["default_model"] == "gpt-5.6-sol"
    assert provider["reasoning_effort"] == "xhigh"

    codex_template = contracts["codex_supervisor"]["template"]
    assert "codex exec --json" in codex_template
    assert '--model "{model_id}"' in codex_template
    assert "model_reasoning_effort=\"xhigh\"" in codex_template
    assert "--sandbox read-only" in codex_template
    assert "--ephemeral" in codex_template
    supervisor_contract = contracts["codex_supervisor"]
    assert supervisor_contract["requested_reasoning_label"] == "extra"
    assert supervisor_contract["resolved_reasoning_effort"] == "xhigh"
    assert supervisor_contract["fallback"] == {"on_binary_missing": "capacity_manager"}
    for tier in ("full", "performance", "low"):
        route = profiles["modes"]["full_cli"]["tiers"][tier]["supervisor"]
        assert route["cli_agent"] == "codex"
        assert route["invocation_contract"] == "codex_supervisor"
        assert route["default"] == "codex_gpt_5_6_sol_xhigh_cli_oauth"


def test_full_cli_codex_workers_only_use_codex_cli_models() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    catalog = _load_config("model_catalog.yml")["models"]
    providers = _load_config("model_providers.yml")["providers"]

    for tier_name, tier in profiles["modes"]["full_cli"]["tiers"].items():
        for role_name, route in tier.items():
            if not isinstance(route, dict) or route.get("cli_agent") != "codex":
                continue
            model = catalog[route["default"]]
            provider = providers[model["runtime_provider"]]
            assert provider["command"] == "codex", f"{tier_name}/{role_name}"


def test_full_cli_deepseek_models_only_use_claude_shell() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    catalog = _load_config("model_catalog.yml")["models"]

    for tier_name, tier in profiles["modes"]["full_cli"]["tiers"].items():
        for role_name, route in tier.items():
            if not isinstance(route, dict):
                continue
            model = catalog[route["default"]]
            if model["provider"] != "deepseek_official":
                continue
            assert route["cli_agent"] == "claude_code", f"{tier_name}/{role_name}"


def test_qwen_role_contract_uses_explicit_dashscope_auth() -> None:
    contract = _load_config("worker_invocation_contracts.yml")["contracts"]["qwen"]

    assert "--auth-type openai" in contract["template"]
    assert "--openai-base-url" in contract["template"]
    assert contract["environment"] == {
        "api_key_source": "DASHSCOPE_API_KEY",
        "api_key_target": "OPENAI_API_KEY",
        "base_url_target": "OPENAI_BASE_URL",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }


def test_narrative_route_does_not_override_model_matrix_contract() -> None:
    configs = _load_config("worker_invocation_contracts.yml")["contracts"]
    routing = _load_config("routing_rules.yml")["routes"][
        "narrative_heavy_audit"
    ]
    contract = configs["qwen_narrative_audit"]

    assert "role_session_contracts" not in routing
    assert contract["worker_id"] == "qwen"
    assert contract["model_profile"] == "qwen3_6_flash_dashscope"
    assert contract["packet_delivery"] == "stdin"
    assert contract["structured_output"] == "narrative_heavy_audit"
    assert "--max-session-turns 6" in contract["template"]
    exclude_value = contract["template"].split("--exclude-tools ", 1)[1].split()[0]
    excluded_tools = set(exclude_value.split(","))
    assert "structured_output" not in excluded_tools
    assert {"read_file", "grep_search", "glob", "list_directory", "agent"} <= excluded_tools
    assert "--core-tools" not in contract["template"]
    assert "--max-tool-calls 1" in contract["template"]
    assert "--json-schema @narrative_heavy_audit_output.schema.json" in contract[
        "template"
    ]
    assert "{task_packet_path}" not in contract["template"]
    assert contract["fallback"] == {"on_binary_missing": "stop_and_report"}


def test_writer_is_claude_deepseek_with_bounded_optional_ultracode() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]
    bindings = _load_config("agent_role_bindings.yml")
    capacity = _load_config("model_capacity.yml")["routes"]

    for tier in ("full", "performance"):
        route = profiles["modes"]["full_cli"]["tiers"][tier]["writer"]
        assert route["cli_agent"] == "claude_code"
        assert route["invocation_contract"] == "claude_writer"
        assert route["default"] == "deepseek_v4_pro"
    writer = contracts["claude_writer"]
    assert '--model "{model_id}"' in writer["template"]
    assert "--effort max" in writer["template"]
    assert "--max-budget-usd" in writer["template"]
    assert "final Chinese prose" in writer["template"]
    assert writer["invocation_style"] == "sealed_packet_stdin"
    assert writer["packet_delivery"] == "stdin"
    assert writer["required_placeholders"] == ["model_id"]
    assert "{task_packet_path}" not in writer["template"]
    assert writer["safe_probe"] == ["claude", "--help"]
    ultracode = contracts["claude_writer_ultracode"]
    assert ultracode["opt_in_only"] is True
    assert ultracode["allowed_work"] == ["developmental_edit", "structure", "continuity", "revision_plan"]
    assert ultracode["forbidden_work"] == ["final_prose_draft"]
    ultracode_route = capacity["WriterUltracode"]
    assert ultracode_route["role"] == "writer"
    assert ultracode_route["worker"] == "claude_code"
    assert ultracode_route["invocation_contract"] == "claude_writer_ultracode"
    assert ultracode_route["model_key"] == "deepseek_v4_pro"
    assert ultracode_route["activation_policy"] == "explicit_sealed_packet_only"
    assert ultracode_route["approved_fallbacks"] == []
    assert "Writer" not in bindings["workers"]["agy"]["allowed_roles"]
    assert "Writer" in bindings["workers"]["claude_code"]["allowed_roles"]


def test_grok_has_separate_research_and_media_contracts() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]
    bindings = _load_config("agent_role_bindings.yml")
    tier = profiles["modes"]["full_cli"]["tiers"]["performance"]

    assert tier["researcher"]["cli_agent"] == "grok"
    assert tier["researcher"]["invocation_contract"] == "grok_research"
    assert tier["artifact_producer"]["invocation_contract"] == "grok_media"
    assert contracts["grok_research"]["worker_id"] == "grok"
    assert "research evidence" in contracts["grok_research"]["template"]
    assert contracts["grok_media"]["worker_id"] == "grok"
    assert "generated artifact paths" in contracts["grok_media"]["template"]
    assert "media_qc_report.yml" not in contracts["grok_media"]["required_receipts"]
    assert "generation_receipt.yml" in contracts["grok_media"]["required_receipts"]
    assert "Observer, Reviewer, and Verifier" in contracts["grok_media"]["template"]
    assert "Researcher" in bindings["workers"]["grok"]["allowed_roles"]
    assert "ArtifactProducer" in bindings["workers"]["grok"]["allowed_roles"]


def test_driver_modes_map_to_agent_backend_modes_without_role_defaults() -> None:
    execution_modes = _load_config("execution_modes.yml")
    backend_modes = set(_load_config("agent_model_profiles.yml")["modes"])

    assert execution_modes["authority"]["purpose"] == "driver_mode_selection"
    assert execution_modes["default_mode"] == "agentlab_orchestrated_cli"
    assert "codex_full_driver" not in execution_modes["execution_modes"]
    assert "codex_coder_only" not in execution_modes["execution_modes"]

    for mode_name, mode in execution_modes["execution_modes"].items():
        assert "agent_backend_mode" in mode
        backend = mode["agent_backend_mode"]
        assert backend in backend_modes, mode_name
        assert mode["allow_worker_all_roles"] is False

        serialized = yaml.safe_dump(mode)
        forbidden_role_keys = (
            "supervisor:",
            "reposcout:",
            "coder:",
            "tester_auditor:",
            "archivist:",
        )
        assert not any(key in serialized for key in forbidden_role_keys)

    retired = execution_modes["legacy_aliases"]["codex_full_driver"]
    assert retired["status"] == "retired"
    assert retired["dispatch_allowed"] is False
    assert retired["replacement"] == "agentlab_orchestrated_cli"


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
