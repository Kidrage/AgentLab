from pathlib import Path

from typer.testing import CliRunner

from agent_runtime.protocols import (
    ARTIFACT_PRODUCER_ROLE,
    build_artifact_task_contract,
    build_role_session,
    infer_artifact_type,
    route_artifact_provider,
    run_artifact_task_doctor,
)
from agent_runtime.run_task import app
from agent_runtime.task_router import recommend_route


ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()


def test_infers_common_artifact_types():
    assert infer_artifact_type("生成图片并导出 png") == "image"
    assert infer_artifact_type("Create an Excel spreadsheet") == "spreadsheet"
    assert infer_artifact_type("写一份报告并生成配图") == "mixed"


def test_artifact_task_contract_routes_to_provider():
    packet = build_artifact_task_contract(
        ROOT,
        "生成一份带图片和表格的交接包",
        artifact_type="mixed",
        project="AgentLab",
        task_id="task_artifact",
    )

    assert packet["packet_type"] == "agentlab_artifact_task"
    assert packet["role"] == ARTIFACT_PRODUCER_ROLE
    assert packet["routing"]["status"] == "routed"
    assert packet["routing"]["selected"]["worker"] in {"codex", "agy", "qwen"}
    assert "validate_artifact_contract" in packet["required_capabilities"]


def test_provider_router_honors_preferred_provider():
    route = route_artifact_provider(
        ROOT,
        "text",
        preferred_provider="agy_cli",
    )

    assert route["status"] == "routed"
    assert route["selected"]["provider_id"] == "agy_cli"
    assert route["selected"]["worker"] == "agy"


def test_pure_artifact_request_routes_to_artifact_producer_not_coder():
    route = recommend_route("请生成一份 markdown 报告和一张 png 图片")

    assert "ArtifactProducer" in route.agents
    assert "Coder" not in route.agents
    assert route.route_key == "artifact_production_task"


def test_mixed_code_and_artifact_request_routes_to_both():
    route = recommend_route("实现导出功能，并生成一个 xlsx 表格样例")

    assert "Coder" in route.agents
    assert "ArtifactProducer" in route.agents
    assert route.agents.index("Coder") < route.agents.index("ArtifactProducer")


def test_artifact_producer_role_session_includes_contract_status():
    packet = build_role_session(ROOT, "ArtifactProducer", "agy", project="AgentLab", task_id="task_missing")

    assert packet["binding"]["allowed"] is True
    assert packet["artifact_task"]["status"] == "missing"
    assert "produce_non_code_artifact_without_artifact_task" in packet["forbidden_actions"]


def test_artifact_doctor_passes():
    result = run_artifact_task_doctor(ROOT)

    assert result["status"] == "pass"
    assert result["summary"]["failed"] == 0


def test_cli_artifact_task_plan_outputs_contract():
    result = runner.invoke(app, [
        "artifact-task-plan",
        "--task-text",
        "生成一份 markdown 报告",
        "--task-id",
        "task_cli_artifact",
    ])

    assert result.exit_code == 0
    assert "packet_type: agentlab_artifact_task" in result.output
    assert "artifact_type: text" in result.output
