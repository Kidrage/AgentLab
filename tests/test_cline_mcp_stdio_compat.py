from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

READ_ONLY_AUTO_APPROVE = {
    "agentlab_get_task_status",
    "agentlab_get_task_events",
    "agentlab_get_task_report",
    "agentlab_list_decisions",
    "agentlab_list_active_skills",
    "agentlab_get_skill_usage",
    "agentlab_webhook_status",
}

STATE_CHANGING_TOOLS = {
    "agentlab_create_task",
    "agentlab_approve_decision",
    "agentlab_reject_decision",
    "agentlab_resume_task",
    "agentlab_pause_task",
    "agentlab_stop_task",
    "agentlab_request_skill_learning",
    "agentlab_approve_skill_request",
    "agentlab_reject_skill_request",
    "agentlab_watchdog_scan",
}


def _run_stdio(messages: list[dict]) -> list[dict]:
    proc = subprocess.run(
        [str(ROOT / "scripts" / "agentlab_mcp_stdio.sh")],
        input="\n".join(json.dumps(msg) for msg in messages) + "\n",
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        env={**os.environ, "AGENTLAB_ROOT": str(ROOT)},
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_wrapper_exists_and_executable() -> None:
    wrapper = ROOT / "scripts" / "agentlab_mcp_stdio.sh"
    assert wrapper.exists()
    assert os.access(wrapper, os.X_OK)


def test_list_tools_command_works() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "agent_runtime.mcp_server", "--list-tools"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["tools"]


def test_initialize_response_shape_and_id_preservation() -> None:
    responses = _run_stdio([
        {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0.1"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
    ])
    assert responses[0]["id"] == "init-1"
    assert responses[0]["result"]["protocolVersion"] == "2025-06-18"
    assert "capabilities" in responses[0]["result"]
    assert responses[0]["result"]["serverInfo"]["name"] == "agentlab"
    assert responses[1]["id"] == 2


def test_tools_list_response_shape_and_descriptions() -> None:
    responses = _run_stdio([{"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list", "params": {}}])
    tools = responses[0]["result"]["tools"]
    assert tools
    for tool in tools:
        assert tool["name"]
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        lowered = tool["description"].lower()
        assert "read-only" in lowered or "state-changing" in lowered
        assert tool["description"] != tool["name"].replace("agentlab_", "AgentLab ").replace("_", " ")


def test_tools_call_read_only_smoke_returns_content_block() -> None:
    responses = _run_stdio([
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {"name": "agentlab_list_active_skills", "arguments": {}},
        }
    ])
    result = responses[0]["result"]
    assert result["isError"] is False
    assert result["content"][0]["type"] == "text"
    assert "skills" in json.loads(result["content"][0]["text"])


def test_unknown_method_returns_jsonrpc_error() -> None:
    responses = _run_stdio([{"jsonrpc": "2.0", "id": "bad-1", "method": "unknown/method", "params": {}}])
    assert responses[0]["id"] == "bad-1"
    assert responses[0]["error"]["code"] == -32601
    assert responses[0]["error"]["message"] == "Method not found"


def test_stdout_cleanliness_for_smoke_input() -> None:
    proc = subprocess.run(
        [str(ROOT / "scripts" / "agentlab_mcp_stdio.sh")],
        input=(
            '{"jsonrpc":"2.0","id":"init-1","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"manual-smoke","version":"0.1"}}}\n'
            '{"jsonrpc":"2.0","id":"tools-1","method":"tools/list","params":{}}\n'
        ),
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        env={**os.environ, "AGENTLAB_ROOT": str(ROOT)},
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 2
    for line in lines:
        assert line.startswith("{")
        json.loads(line)


def test_config_examples_are_valid_json_and_cline_shaped() -> None:
    for path in (ROOT / "examples" / "cline").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "mcpServers" in data
        agentlab = data["mcpServers"]["agentlab"]
        assert agentlab["command"]
        assert agentlab["args"]
        assert "env" in agentlab
        assert agentlab["disabled"] is False
        assert isinstance(agentlab["autoApprove"], list)


def test_autoapprove_examples_are_read_only_only() -> None:
    for path in (ROOT / "examples" / "cline").glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        auto_approve = set(data["mcpServers"]["agentlab"]["autoApprove"])
        assert auto_approve <= READ_ONLY_AUTO_APPROVE
        assert not (auto_approve & STATE_CHANGING_TOOLS)
