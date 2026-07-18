from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.workers.command_template_validator import validate_template
from agent_runtime.workers.invocation_contract import load_contracts


ROOT = Path(__file__).resolve().parents[1]


def _yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8")) or {}


def test_all_endpoints_and_agents_publish_peer_directory() -> None:
    directory = _yaml("shared_agent_directory.yml")
    endpoints = directory["endpoints"]
    agents = directory["agents"]

    assert {"local_source", "relay_hub", "cloud_runtime", "localization_69"}.issubset(endpoints)
    assert all(endpoint.get("peer_awareness_required") is True for endpoint in endpoints.values())
    assert endpoints["localization_69"]["status"] in {"inventory_required", "ready", "blocked"}
    assert {
        "agentlab",
        "openclaw",
        "hermes",
        "codex",
        "claude_code",
        "qwen",
        "agy",
        "bl",
    }.issubset(agents)
    assert directory["services"]["agentlab_mcp"]["port"] is None
    assert directory["network_policy"]["public_bind_default"] == "forbidden"


def test_frontdesk_named_delegation_is_relay_only() -> None:
    collaboration = _yaml("agent_collaboration.yml")["agent_collaboration"]
    policy = collaboration["explicit_named_delegation"]

    assert policy["dispatcher_may_execute_task"] is False
    assert policy["named_agent_unavailable"] == "stop_and_report"
    assert "implement_task_itself" in policy["dispatcher_forbidden_actions"]
    assert "actual_changed_files" in policy["result_report_must_include"]


def test_capability_route_is_local_and_deterministic_first() -> None:
    policy = _yaml("capability_routing_policy.yml")
    route = policy["route_order"]

    assert route[0] == "local_deterministic_tool"
    assert route.index("verified_local_skill") < route.index("local_agent_cli")
    assert route.index("local_agent_cli") < route.index("approved_cloud_specialist")
    assert policy["fallback_policy"]["automatic_fallback_allowed"] is False
    assert policy["managed_skill_overrides"]["bailian-cli"]["universal_ai_task_trigger"] == "forbidden"


def test_registered_worker_templates_parse_and_have_no_legacy_fake_commands() -> None:
    contracts = load_contracts(ROOT / "config" / "worker_invocation_contracts.yml")
    forbidden = ("codex --task", "claude --task", "agy --task", "bl chat", "openclaw run")

    for contract in contracts.values():
        assert not any(pattern in contract.template for pattern in forbidden)
        valid, errors = validate_template(
            contract.template,
            contract.required_placeholders,
            allow_unquoted_placeholders=contract.validation.allow_unquoted_placeholders,
        )
        assert valid, f"{contract.worker_id}: {errors}"


def test_runtime_profiles_do_not_contain_legacy_fake_commands() -> None:
    text = (ROOT / "config" / "agent_model_profiles.yml").read_text(encoding="utf-8")
    for pattern in ("claude --task", "agy --task", "codex --task", "--max-quality", "--fast"):
        assert pattern not in text


def test_authoritative_protocol_points_to_structured_policies() -> None:
    protocol = (ROOT / "_shared" / "AGENT_PROTOCOL.md").read_text(encoding="utf-8")
    assert "config/shared_agent_directory.yml" in protocol
    assert "config/capability_routing_policy.yml" in protocol
    assert "config/repository_handoff_policy.yml" in protocol
    assert "PROJECT_HANDOFF.md" in protocol
    assert "relay_only" in protocol
    assert "Localization 69" in protocol
    assert "repository-handoff --repo <path> --write" in protocol


def test_cli_homes_are_local_only_and_excluded_from_repository_ingestion() -> None:
    protocol = (ROOT / "_shared" / "AGENT_PROTOCOL.md").read_text(encoding="utf-8")
    collaboration = (
        ROOT / "docs" / "AGENTLAB_CORP_AND_COLLABORATION_PROTOCOL.md"
    ).read_text(encoding="utf-8")
    glossary = (ROOT / "CONTEXT.md").read_text(encoding="utf-8")
    ingestion = _yaml("repo_ingestion_policy.yml")["repo_ingestion"]

    assert "`.agents/` (locks, states)" in protocol
    assert "不得通过 Git 或 Relay Hub 同步" in collaboration
    assert "local-only" in glossary
    assert ".agents/**" in ingestion["default_excludes"]


def test_repository_handoff_is_mandatory_for_every_agent() -> None:
    policy = _yaml("repository_handoff_policy.yml")
    collaboration = _yaml("agent_collaboration.yml")["agent_collaboration"]
    directory = _yaml("shared_agent_directory.yml")

    assert "PROJECT_HANDOFF.md" in policy["discovery"]["filenames"]
    assert policy["discovery"]["always_before_repository_read"] is True
    assert policy["placement"]["project_root_visible"] == "PROJECT_HANDOFF.md"
    assert policy["placement"]["always_write_project_root_visible_copy"] is True
    assert policy["enforcement"]["all_agents_required"] is True
    assert policy["enforcement"]["missing_handoff_blocks_deep_read"] is True
    assert policy["placement"]["always_write_shared_copy"] is True
    assert policy["safe_scan"]["principle"] == "complete_path_and_metadata_inventory_without_bulk_content_read"
    assert collaboration["repository_handoff"]["required_for_all_agents"] is True
    assert directory["repository_memory"]["applies_to_all_endpoints_and_agents"] is True


def test_agent_execution_paths_receive_repository_handoff_gate() -> None:
    runner = (ROOT / "agent_runtime" / "agent_runner.py").read_text(encoding="utf-8")
    cli_executor = (ROOT / "agent_runtime" / "cli_executor.py").read_text(encoding="utf-8")

    assert "Before reading repository/project content" in runner
    assert '"repository_handoff"' in cli_executor
    assert '"refresh_before_final_report": True' in cli_executor


def test_shadow_sg_is_not_registered_as_ast_grep() -> None:
    capability_defaults = _yaml("worker_capability_defaults.yml")["workers"]
    assignment = _yaml("role_assignment_policy.yml")["roles"]["InterfaceMapper"]["candidates"]
    assert "sg" not in capability_defaults
    assert "sg" not in assignment
