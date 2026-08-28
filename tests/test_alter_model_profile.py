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
    assert resolved["invocation_contract"] == "hermes_supervisor"
    assert resolved["default"] == "codex_gpt_5_6_sol_xhigh_hermes_oauth"


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


def test_alter_tier_uses_codex_agy_hermes_and_isolated_claude_without_grok() -> None:
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
    assert {cfg["cli_agent"] for cfg in alter.values()} == {
        "hermes",
        "agy",
        "codex",
        "claude_code",
    }

    expected = {
        "supervisor": ("hermes", "hermes_supervisor", "codex_gpt_5_6_sol_xhigh_hermes_oauth"),
        "observer": ("agy", "agy_observer", "gemini_3_6_flash_high_agy_oauth"),
        "reposcout": ("codex", "codex", "codex_gpt_5_6_sol_high_cli_oauth"),
        "interface_mapper": ("codex", "codex", "codex_gpt_5_6_sol_xhigh_cli_oauth"),
        "researcher": ("agy", "agy_research", "gemini_3_6_flash_high_agy_oauth"),
        "prompt_engineer": ("hermes", "hermes_deepseek", "deepseek_v4_flash_hermes_private"),
        "coder": ("codex", "codex", "codex_gpt_5_6_sol_xhigh_cli_oauth"),
        "artifact_producer": ("codex", "codex", "codex_gpt_5_6_sol_medium_cli_oauth"),
        "narrative_planner": ("agy", "agy_narrative_planner", "gemini_3_6_flash_high_agy_oauth"),
        "tester_auditor": ("hermes", "hermes_deepseek", "deepseek_v4_flash_hermes_private"),
        "verifier": ("hermes", "hermes_deepseek", "deepseek_v4_flash_hermes_private"),
        "archivist": ("hermes", "hermes_deepseek", "deepseek_v4_flash_hermes_private"),
        "writer": ("claude_code", "claude_writer", "deepseek_v4_pro"),
        "reviewer": ("agy", "agy_reviewer", "gemini_3_6_flash_high_agy_oauth"),
        "visual_reviewer": ("agy", "agy_visual_reviewer", "gemini_3_6_flash_high_agy_oauth"),
        "scribe": ("agy", "agy_scribe", "gemini_3_6_flash_high_agy_oauth"),
    }
    for role, (worker, contract, model) in expected.items():
        assert (
            alter[role]["cli_agent"],
            alter[role]["invocation_contract"],
            alter[role]["default"],
        ) == (worker, contract, model)

    serialized = yaml.safe_dump(alter)
    assert "grok" not in serialized.lower()
    assert "xai" not in serialized.lower()


def test_alter_capacity_routes_are_exact_and_do_not_fallback_to_grok() -> None:
    profiles = _yaml("config/agent_model_profiles.yml")
    capacity = _yaml("config/model_capacity.yml")
    routes = capacity["routes"]
    alter = profiles["modes"]["full_cli"]["tiers"]["alter"]

    for role, profile in alter.items():
        route = routes[profile["capacity_route"]]
        assert route["worker"] == profile["cli_agent"]
        assert route["invocation_contract"] == profile["invocation_contract"]
        assert route["model_key"] == profile["default"]
        if role in {"observer", "narrative_planner", "writer", "reviewer", "visual_reviewer", "scribe"}:
            continue
        assert route["approved_fallbacks"] == [], role
        assert route["fallback_on"] == [], role
        assert "grok" not in yaml.safe_dump(route).lower(), role


def test_alter_text_artifact_dispatch_uses_codex_without_media_generation() -> None:
    policy = _yaml("config/artifact_task_policy.yml")
    provider = policy["providers"]["codex_cli"]

    assert provider["worker"] == "codex"
    assert provider["invocation_contract"] == "codex"
    assert provider["capacity_routes"]["alter"] == "AlterArtifactProducer"
    assert provider["handles"] == ["text"]
    assert not any(
        {"image", "video"}.intersection(candidate.get("handles", []))
        for candidate in policy["providers"].values()
        if candidate.get("availability", "active")
        not in {"pending_local_model", "historical_only"}
    )
