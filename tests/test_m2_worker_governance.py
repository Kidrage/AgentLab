from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from agent_runtime.capabilities.capability_schema import CapabilitySchema
from agent_runtime.capabilities.compatibility import (
    CompatibilityChecker,
    WorkerCapabilityRegistry,
)
from agent_runtime.capabilities.role_requirements import RoleRequirementsRegistry
from agent_runtime.execution_economy.role_activation_policy import RoleActivationPolicy
from agent_runtime.execution_economy.role_coalescing import coalesce_roles
from agent_runtime.routing.fallback_policy import WorkerFallbackPolicy
from agent_runtime.routing.mode_tier_policy import ModeTierWorkerPolicy
from agent_runtime.run_task import app
from agent_runtime.workers.invocation_contract import (
    WorkerInvocationContract,
    load_contracts,
)
from agent_runtime.workers.registry import WorkerRegistry


ROOT = Path(__file__).resolve().parents[1]


def test_mode_tier_prefers_deterministic_workers_and_enforces_risk() -> None:
    policy = ModeTierWorkerPolicy(ROOT / "config" / "mode_tier_worker_policy.yml")
    ranked = policy.rank(
        ["claude_code", "rg"],
        "RepoScout",
        "hybrid_local_company",
        "performance",
    )
    assert ranked[0] == "rg"
    assert policy.permits("claude_code", "high", "hybrid_local_company", "low")[0] is False


def test_role_activation_defaults_and_expected_benefit() -> None:
    policy = RoleActivationPolicy()
    assert policy.get_candidate_worker("Supervisor") == "claude_code"
    assert policy.get_candidate_worker("RepoScout") == "rg"
    assert policy.get_candidate_worker("Verifier") == "ruff"
    assert policy.get_expected_benefit("Coder", "medium")["quality_gain"] == "high"
    assert policy.get_expected_benefit("Coder", "small")["quality_gain"] == "medium"


def test_small_task_role_coalescing() -> None:
    packets = coalesce_roles(
        ["Supervisor", "PromptEngineer", "Coder", "RepoScout"],
        task_size="small",
    )

    assert len(packets) == 2
    by_id = {packet.coalesced_packet_id: packet for packet in packets}
    assert set(by_id) == {"coalesced_coder_packet", "single_reposcout_packet"}
    assert set(by_id["coalesced_coder_packet"].roles) == {
        "Supervisor",
        "PromptEngineer",
        "Coder",
    }
    assert by_id["coalesced_coder_packet"].selected_worker == "claude_code"


def test_coder_fallback_order() -> None:
    policy = WorkerFallbackPolicy(ROOT / "config" / "worker_fallback_policy.yml")
    assert policy.fallbacks("Coder", "claude_code")[:2] == ["codex", "aider"]


def test_worker_invocation_contracts_and_shell_capabilities() -> None:
    config_path = ROOT / "config" / "worker_invocation_contracts.yml"
    contracts = load_contracts(config_path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    hermes = contracts["hermes"]
    assert isinstance(hermes, WorkerInvocationContract)
    assert hermes.command == "hermes"
    assert hermes.invocation_style == "one_shot_prompt"
    assert "task_packet_path" in hermes.required_placeholders
    assert hermes.validation.shlex_parse_required is True

    for worker in (
        "hermes",
        "claude",
        "codex",
        "qwen",
        "agy",
        "agy_coder",
        "agy_writer",
    ):
        assert raw["contracts"][worker]["workflow_shell"] is True
    capabilities = {
        worker: set(raw["contracts"][worker]["workflow_shell_capability_families"])
        for worker in ("hermes", "claude", "codex", "qwen", "agy_coder")
    }
    assert {
        "tool_and_mcp_governance",
        "native_command_surface_inventory",
        "collaboration_board_governance",
    } <= capabilities["hermes"]
    assert {
        "worktree_or_background_execution",
        "native_subagent_orchestration",
    } <= capabilities["claude"]
    assert "permission_and_sandbox_control" in capabilities["codex"]
    assert "structured_output_and_qc" in capabilities["qwen"]
    assert "workspace_context_control" in capabilities["agy_coder"]
    assert raw["contracts"]["agy_writer"]["invocation_style"] == "sealed_task_packet_prompt"

    grok = contracts["grok"]
    assert grok.command == "hermes"
    assert grok.invocation_style == "media_backend_task_packet"
    assert "task_packet_path" in grok.required_placeholders
    assert "XAI_API_KEY" not in grok.template
    assert "Hermes xAI OAuth Grok session" in grok.template
    assert raw["contracts"]["grok"]["workflow_shell_backend"] == "hermes"


def test_worker_registry_scan_and_cache(tmp_path) -> None:
    registry = WorkerRegistry(tmp_path)
    assert registry.load_from_cache() is False

    registry.scan_and_register()

    cache_file = tmp_path / "worker_registry.yml"
    assert cache_file.is_file()
    content = yaml.safe_load(cache_file.read_text(encoding="utf-8"))
    assert content["workers"]

    restored = WorkerRegistry(tmp_path)
    assert restored.load_from_cache() is True
    assert len(restored.list_workers()) == len(registry.list_workers())
    assert restored.get_worker("git").worker_id == "git"


def _compatibility_checker() -> tuple[
    CompatibilityChecker,
    CapabilitySchema,
    RoleRequirementsRegistry,
]:
    schema = CapabilitySchema.load_from_file(ROOT / "config" / "capability_schema.yml")
    roles = RoleRequirementsRegistry.load_from_file(
        ROOT / "config" / "agent_role_requirements.yml"
    )
    workers = WorkerCapabilityRegistry.load_from_file(
        ROOT / "config" / "worker_capability_defaults.yml"
    )
    return CompatibilityChecker(schema, roles, workers), schema, roles


def test_role_worker_compatibility_rules() -> None:
    checker, schema, roles = _compatibility_checker()

    for worker, role in (("rg", "Coder"), ("pytest", "Supervisor")):
        compatible, reason = checker.is_compatible(worker, role)
        assert compatible is False
        assert "lacks required capability" in reason
    assert checker.is_compatible("claude_code", "Coder")[0] is True
    for worker in ("hermes", "gemini", "qwen"):
        assert checker.is_compatible(worker, "Supervisor")[0] is True
    cloud_upload = schema.get_capability("cloud_upload")
    assert cloud_upload is not None
    assert cloud_upload.risk_level == "high"
    assert roles.get_role_requirements("supervisor") is not None
    assert checker.requires_approval_for_assignment("claude_code", "Supervisor")[0]


def test_role_compatible_workers_cli() -> None:
    result = CliRunner().invoke(app, ["role-compatible-workers", "--role", "RepoScout"])
    assert result.exit_code == 0
    assert "rg" in result.stdout
    assert "YES" in result.stdout
    assert "claude_code" in result.stdout
    assert "NO" in result.stdout
    assert "forbidden" in result.stdout


def test_role_requirements_and_cli() -> None:
    registry = RoleRequirementsRegistry.load_from_file(
        ROOT / "config" / "agent_role_requirements.yml"
    )
    assert len(registry.list_roles()) == 10

    coder = registry.get_role_requirements("Coder")
    assert coder is not None
    assert {"file_edit", "patch_generation"} <= set(coder.required_capabilities)
    assert coder.default_risk_ceiling == "high"
    artifact = registry.get_role_requirements("ArtifactProducer")
    assert artifact is not None
    assert {"artifact_task_contract", "write_artifact_file"} <= set(
        artifact.required_capabilities
    )
    supervisor = registry.get_role_requirements("supervisor")
    assert supervisor == registry.get_role_requirements("Supervisor")
    assert {"planning", "task_decomposition"} <= set(supervisor.required_capabilities)

    runner = CliRunner()
    listed = runner.invoke(app, ["role-requirements"])
    assert listed.exit_code == 0
    assert "coder" in listed.stdout.lower()
    assert "supervisor" in listed.stdout.lower()
    assert "artifact" in listed.stdout.lower()
    inspected = runner.invoke(app, ["role-inspect", "--role", "Coder"])
    assert inspected.exit_code == 0
    assert "file_edit" in inspected.stdout
    assert "patch_generation" in inspected.stdout
    assert "HIGH" in inspected.stdout
    invalid = runner.invoke(app, ["role-inspect", "--role", "InvalidRoleName"])
    assert invalid.exit_code != 0
    assert "Error: Unknown role" in invalid.stdout
