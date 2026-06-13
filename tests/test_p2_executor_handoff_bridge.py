from pathlib import Path

from agent_runtime.executors import ExecutionRequest, load_executor_providers, load_executor_router_policy, route_execution_request
from agent_runtime.executors.handoff_bridge import create_execution_plan


def _manual_decision(tmp_path):
    policy = load_executor_router_policy(Path("config/executor_router.yml"))
    policy.routing["allow_mock_executor"] = False
    policy.provider_priority["repo_patch"] = ["manual.codex"]
    providers = load_executor_providers(policy)
    request = ExecutionRequest(
        task_id="manual",
        task_type="repo_patch",
        summary="Patch via handoff",
        allowed_files=["agent_runtime/demo.py"],
        forbidden_files=[".env"],
        required_capabilities=["repo_patch"],
        evidence_required=["execution_result_envelope.yml"],
    )
    decision = route_execution_request(request, providers, policy)
    plan = create_execution_plan(request, decision, policy, tmp_path, providers=providers)
    return tmp_path, plan


def test_manual_handoff_contains_required_sections(tmp_path):
    out, _ = _manual_decision(tmp_path)
    text = (out / "external_execution_handoff.md").read_text()
    for section in ["Task Summary", "Selected Provider", "Scope", "Required Tests", "P2-A Review Requirement"]:
        assert f"## {section}" in text


def test_manual_handoff_contains_safety_constraints(tmp_path):
    out, _ = _manual_decision(tmp_path)
    text = (out / "external_execution_handoff.md").read_text()
    assert "Do not expose secrets." in text
    assert "Do not start MCP servers." in text
    assert "Do not copy third-party source code." in text


def test_manual_handoff_requires_result_envelope(tmp_path):
    out, _ = _manual_decision(tmp_path)
    assert "Return result as ExecutionResultEnvelope." in (out / "external_execution_handoff.md").read_text()


def test_needs_approval_generates_approval_artifact(tmp_path):
    out, plan = _manual_decision(tmp_path)
    assert plan.approval_required is True
    assert (out / "approval_required.yml").is_file()
