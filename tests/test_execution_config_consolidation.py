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


def test_agent_model_profiles_delegate_dynamic_fallbacks_to_runtime_registry() -> None:
    profiles = _load_config("agent_model_profiles.yml")

    authority = profiles["authority"]
    assert authority["automatic_fallback_source"] == "config/runtime_registry.yml"
    assert authority["legacy_capacity_source"] == "config/model_capacity.yml"
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

    assert tier["supervisor"]["cli_agent"] == "hermes"
    assert tier["supervisor"]["invocation_contract"] == "hermes_supervisor"
    assert tier["supervisor"]["default"] == "codex_gpt_5_5_high_hermes_oauth"
    assert "capacity_route" not in tier["supervisor"]
    assert tier["observer"]["cli_agent"] == "agy"
    assert tier["observer"]["invocation_contract"] == "agy_observer"

    assert tier["reposcout"]["cli_agent"] == "claude_code"
    assert tier["reposcout"]["default"] == "deepseek_v4_pro"

    assert tier["interface_mapper"]["cli_agent"] == "claude_code"
    assert tier["interface_mapper"]["default"] == "deepseek_v4_pro"

    assert tier["researcher"]["cli_agent"] == "agy"
    assert tier["researcher"]["invocation_contract"] == "agy_observer"
    assert tier["researcher"]["default"] == "gemini_3_5_flash_high_agy_oauth"

    assert tier["prompt_engineer"]["cli_agent"] == "claude_code"
    assert tier["prompt_engineer"]["default"] == "deepseek_v4_pro"

    assert tier["coder"]["cli_agent"] == "claude_code"
    assert tier["coder"]["default"] == "deepseek_v4_pro"

    assert tier["artifact_producer"]["cli_agent"] == "claude_code"
    assert tier["artifact_producer"]["invocation_contract"] == "claude"
    assert tier["artifact_producer"]["default"] == "deepseek_v4_pro"
    assert "artifact_backend" not in tier["artifact_producer"]

    assert tier["tester_auditor"]["cli_agent"] == "claude_code"
    assert tier["tester_auditor"]["default"] == "deepseek_v4_pro"

    assert tier["verifier"]["cli_agent"] == "claude_code"
    assert tier["verifier"]["default"] == "deepseek_v4_pro"

    assert tier["archivist"]["cli_agent"] == "claude_code"
    assert tier["archivist"]["default"] == "deepseek_v4_flash"

    assert tier["writer"]["cli_agent"] == "claude_code"
    assert tier["writer"]["invocation_contract"] == "claude_writer"
    assert tier["writer"]["default"] == "deepseek_v4_pro"
    assert "capacity_route" not in tier["writer"]


def test_full_cli_full_tier_matches_operator_matrix() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    tier = profiles["modes"]["full_cli"]["tiers"]["full"]

    assert tier["supervisor"]["cli_agent"] == "hermes"
    assert tier["supervisor"]["invocation_contract"] == "hermes_supervisor"
    assert tier["supervisor"]["default"] == "codex_gpt_5_5_high_hermes_oauth"
    assert tier["observer"]["invocation_contract"] == "agy_observer"

    assert tier["reposcout"]["cli_agent"] == "claude_code"
    assert tier["reposcout"]["default"] == "deepseek_v4_pro"

    assert tier["interface_mapper"]["cli_agent"] == "claude_code"
    assert tier["interface_mapper"]["default"] == "deepseek_v4_pro"

    assert tier["researcher"]["cli_agent"] == "agy"
    assert tier["researcher"]["invocation_contract"] == "agy_observer"
    assert tier["researcher"]["default"] == "gemini_3_5_flash_high_agy_oauth"

    assert tier["prompt_engineer"]["cli_agent"] == "claude_code"
    assert tier["prompt_engineer"]["default"] == "deepseek_v4_pro"

    assert tier["coder"]["cli_agent"] == "claude_code"
    assert tier["coder"]["default"] == "deepseek_v4_pro"

    assert tier["tester_auditor"]["cli_agent"] == "claude_code"
    assert tier["tester_auditor"]["default"] == "deepseek_v4_pro"

    assert tier["verifier"]["cli_agent"] == "claude_code"
    assert tier["verifier"]["default"] == "deepseek_v4_pro"

    assert tier["archivist"]["cli_agent"] == "claude_code"
    assert tier["archivist"]["default"] == "deepseek_v4_pro"

    assert tier["artifact_producer"]["cli_agent"] == "claude_code"
    assert tier["artifact_producer"]["invocation_contract"] == "claude"
    assert tier["writer"]["cli_agent"] == "claude_code"
    assert tier["writer"]["invocation_contract"] == "claude_writer"
    assert tier["writer"]["default"] == "deepseek_v4_pro"
    assert "capacity_route" not in tier["writer"]


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
    assert tier["artifact_producer"]["cli_agent"] == "claude_code"
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


def test_hermes_supervisor_uses_registered_gpt_55_high_route() -> None:
    profiles = _load_config("agent_model_profiles.yml")
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
    assert model["reasoning_effort_label"] == "high"
    assert _cost_source(model, {}) == "oauth/subscription quota"

    provider = providers["openai-codex"]
    assert provider["type"] == "oauth_cli"
    assert provider["command"] == "hermes"
    assert provider["default_model"] == "gpt-5.5"
    assert provider["reasoning_effort"] == "high"

    hermes_template = contracts["hermes_supervisor"]["template"]
    assert "-p agentlabsupervisor chat -Q" in hermes_template
    assert "--provider {provider}" in hermes_template
    assert "-m {model_id}" in hermes_template
    assert " -q " in hermes_template
    assert " -z " not in hermes_template
    supervisor_contract = contracts["hermes_supervisor"]
    assert supervisor_contract["workflow_shell_profile"] == "agentlabsupervisor"
    assert supervisor_contract["requested_reasoning_label"] == "high"
    assert supervisor_contract["resolved_reasoning_effort"] == "high"
    assert supervisor_contract["required_shell_state"] == {
        "model.provider": "openai-codex",
        "model.default": "gpt-5.5",
        "agent.reasoning_effort": "high",
        "fallback_providers": [],
        "fallback_model": None,
    }
    for tier in ("full", "performance", "low"):
        route = profiles["modes"]["full_cli"]["tiers"][tier]["supervisor"]
        assert route["invocation_contract"] == "hermes_supervisor"
        assert route["default"] == "codex_gpt_5_5_high_hermes_oauth"


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


def test_grok_contracts_remain_registered_but_quarantined_from_default_routes() -> None:
    profiles = _load_config("agent_model_profiles.yml")
    contracts = _load_config("worker_invocation_contracts.yml")["contracts"]
    bindings = _load_config("agent_role_bindings.yml")
    tier = profiles["modes"]["full_cli"]["tiers"]["performance"]

    runtime = _load_config("runtime_registry.yml")
    assert tier["researcher"]["cli_agent"] == "agy"
    assert tier["artifact_producer"]["cli_agent"] == "claude_code"
    assert runtime["providers"]["xai_oauth"]["status"] == "quarantined"
    assert runtime["models"]["grok_4_3_oauth_quarantined"]["status"] == "quarantined"
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
