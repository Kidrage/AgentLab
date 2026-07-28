from pathlib import Path

import yaml

from agent_runtime.cli_executor import budget_mode_to_tier, resolve_cli_profile
from agent_runtime.run_task import _configured_tiers_for_update
from agent_runtime.workflow_plan import _budget_mode_from_request, _resolve_budget_mode


ROOT = Path(__file__).resolve().parents[1]


def _yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8")) or {}


def test_alter_is_the_default_subscription_first_tier() -> None:
    profiles = _yaml("config/agent_model_profiles.yml")
    execution = _yaml("config/execution_policy.yml")

    assert profiles["tier_policy"]["default_tier"] == "alter"
    assert execution["budget_mode_policy"]["default_budget_mode"] == "alter"
    assert _resolve_budget_mode({"execution_policy": execution}, "") == "alter"
    assert budget_mode_to_tier("alter") == "alter"
    assert budget_mode_to_tier("altered") == "alter"

    resolved = resolve_cli_profile(profiles, agent_role="supervisor")
    assert resolved is not None
    assert resolved["resolved_tier"] == "alter"
    assert resolved["cli_agent"] == "hermes"
    assert resolved["default"] == "grok_4_5_hermes_oauth"


def test_alter_keyword_is_an_exact_task_trigger() -> None:
    assert _budget_mode_from_request("alter") == "alter"
    assert _budget_mode_from_request("  alter  \n") == "alter"
    assert _budget_mode_from_request("budget_mode: alter") == "alter"
    assert _budget_mode_from_request("please alter the file") is None


def test_configure_agent_updates_only_tiers_declared_by_each_mode() -> None:
    assert _configured_tiers_for_update(
        {"alter": {}, "full": {}, "performance": {}, "low": {}},
        None,
    ) == ["alter", "full", "performance", "low"]
    assert _configured_tiers_for_update(
        {"full": {}, "performance": {}, "low": {}},
        None,
    ) == ["full", "performance", "low"]
    assert _configured_tiers_for_update({"full": {}}, "ALTER") == ["alter"]


def test_alter_tier_routes_grok_work_through_hermes_and_keeps_agy_primaries() -> None:
    profiles = _yaml("config/agent_model_profiles.yml")
    alter = profiles["modes"]["full_cli"]["tiers"]["alter"]
    assert {role for role in alter} == {
        key
        for key in (
            "supervisor",
            "observer",
            "reposcout",
            "interface_mapper",
            "researcher",
            "prompt_engineer",
            "coder",
            "artifact_producer",
            "narrative_planner",
            "tester_auditor",
            "verifier",
            "archivist",
            "writer",
            "reviewer",
            "visual_reviewer",
            "scribe",
        )
    }
    assert {cfg["cli_agent"] for cfg in alter.values()} == {"hermes", "agy"}

    assert alter["supervisor"]["invocation_contract"] == "hermes_alter_high"
    for role, cfg in alter.items():
        if cfg["cli_agent"] == "hermes":
            assert cfg["default"] == "grok_4_5_hermes_oauth", role
            assert cfg["reasoning_effort"] == "high", role

    contracts = _yaml("config/worker_invocation_contracts.yml")["contracts"]
    for contract_name in {"hermes_alter_high", "hermes_alter_artifact"}:
        contract = contracts[contract_name]
        assert contract["worker_id"] == "hermes"
        assert contract["workflow_shell_profile"] == "agentlabalter"
        assert contract["required_shell_state"] == {
            "model.provider": "xai-oauth",
            "model.default": "grok-4.5",
            "agent.reasoning_effort": "high",
            "fallback_providers": [],
            "fallback_model": None,
        }
        assert "hermes -p agentlabalter chat -Q" in contract["template"]


def test_alter_capacity_routes_have_governed_deepseek_fallbacks() -> None:
    profiles = _yaml("config/agent_model_profiles.yml")
    capacity = _yaml("config/model_capacity.yml")
    routes = capacity["routes"]
    alter = profiles["modes"]["full_cli"]["tiers"]["alter"]

    multimodal_exceptions = {"observer", "visual_reviewer"}
    for role, profile in alter.items():
        route = routes[profile["capacity_route"]]
        assert route["worker"] == profile["cli_agent"]
        assert route["invocation_contract"] == profile["invocation_contract"]
        assert route["model_key"] == profile["default"]
        assert route["approved_fallbacks"], role
        fallback = routes[route["approved_fallbacks"][0]]
        if role in multimodal_exceptions:
            assert fallback["worker"] == "agy"
            assert fallback["model_key"] == "claude_sonnet_4_6_agy_oauth"
        elif role == "artifact_producer":
            assert fallback["worker"] == "codex"
            assert fallback["model_key"] == "codex_gpt_5_6_sol_medium_cli_oauth"
        else:
            assert fallback["worker"] == "claude_code"
            assert fallback["model_key"] in {"deepseek_v4_pro", "deepseek_v4_flash"}


def test_alter_artifact_dispatch_uses_the_hermes_grok_artifact_contract() -> None:
    policy = _yaml("config/artifact_task_policy.yml")
    provider = policy["providers"]["hermes_grok"]

    assert provider["worker"] == "hermes"
    assert provider["invocation_contract"] == "hermes_alter_artifact"
    assert provider["capacity_routes"]["alter"] == "AlterArtifactProducer"
