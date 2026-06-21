"""Tests for WorkerInvocationContract schema and load functions."""

from pathlib import Path
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
