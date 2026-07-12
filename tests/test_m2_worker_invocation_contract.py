"""Tests for WorkerInvocationContract schema and load functions."""

from pathlib import Path
import yaml
from agent_runtime.workers.invocation_contract import load_contracts, WorkerInvocationContract

def test_load_contracts():
    config_path = Path(__file__).resolve().parents[1] / "config" / "worker_invocation_contracts.yml"
    contracts = load_contracts(config_path)

    assert len(contracts) > 0
    assert "hermes" in contracts
    assert "claude" in contracts

    c = contracts["hermes"]
    assert isinstance(c, WorkerInvocationContract)
    assert c.worker_id == "hermes"
    assert c.command == "hermes"
    assert c.invocation_style == "one_shot_prompt"
    assert "task_packet_path" in c.required_placeholders
    assert c.validation.shlex_parse_required is True

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert raw["contracts"]["hermes"]["workflow_shell"] is True
    assert raw["contracts"]["claude"]["workflow_shell"] is True
    assert raw["contracts"]["codex"]["workflow_shell"] is True
    assert raw["contracts"]["qwen"]["workflow_shell"] is True
    assert raw["contracts"]["agy"]["workflow_shell"] is True
    assert raw["contracts"]["agy_coder"]["workflow_shell"] is True
    assert raw["contracts"]["agy_writer"]["workflow_shell"] is True
    assert "tool_and_mcp_governance" in raw["contracts"]["hermes"]["workflow_shell_capability_families"]
    assert "native_command_surface_inventory" in raw["contracts"]["hermes"]["workflow_shell_capability_families"]
    assert "collaboration_board_governance" in raw["contracts"]["hermes"]["workflow_shell_capability_families"]
    assert "worktree_or_background_execution" in raw["contracts"]["claude"]["workflow_shell_capability_families"]
    assert "native_subagent_orchestration" in raw["contracts"]["claude"]["workflow_shell_capability_families"]
    assert "permission_and_sandbox_control" in raw["contracts"]["codex"]["workflow_shell_capability_families"]
    assert "structured_output_and_qc" in raw["contracts"]["qwen"]["workflow_shell_capability_families"]
    assert "workspace_context_control" in raw["contracts"]["agy_coder"]["workflow_shell_capability_families"]
    assert raw["contracts"]["agy_writer"]["invocation_style"] == "sealed_task_packet_prompt"

    grok = contracts["grok"]
    assert grok.worker_id == "grok"
    assert grok.command == "hermes"
    assert grok.invocation_style == "media_backend_task_packet"
    assert "task_packet_path" in grok.required_placeholders
    assert "XAI_API_KEY" not in grok.template
    assert "Hermes xAI OAuth Grok session" in grok.template
    assert raw["contracts"]["grok"]["workflow_shell_backend"] == "hermes"
