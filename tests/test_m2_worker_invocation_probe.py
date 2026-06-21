"""Tests for worker invocation contract parsing and safe probing."""

import shlex
from agent_runtime.workers.invocation_contract import WorkerInvocationContract
from agent_runtime.workers.safe_probe_runner import run_safe_probe

def test_hermes_template_parse():
    # Hermes contract template
    template = 'hermes -z "You are an AgentLab CLI executor. Read the JSON task packet at {task_packet_path}"'
    
    # Render with a task packet path
    task_packet_path = "/tmp/task_packet.json"
    cmd_str = template.format(task_packet_path=task_packet_path)
    
    # Parse with shlex
    argv = shlex.split(cmd_str)
    
    assert argv[0] == "hermes"
    assert argv[1] == "-z"
    assert "Read the JSON task packet at /tmp/task_packet.json" in argv[2]

def test_mock_safe_probe():
    contract = WorkerInvocationContract(
        worker_id="hermes",
        display_name="Hermes CLI",
        command="hermes",
        invocation_style="one_shot_prompt",
        template="hermes -z {task_packet_path}",
        safe_probe=["hermes", "--help"]
    )
    
    # Probe with mock = True
    exit_code, stdout, stderr, timeout, bin_missing = run_safe_probe(contract, mock=True)
    
    # Since mock = True, simulated command check will happen. If hermes is installed on the mac,
    # it returns 0. If not, it returns None and bin_missing=True. Either way it's a valid mock return.
    assert exit_code == 0 or bin_missing is True
