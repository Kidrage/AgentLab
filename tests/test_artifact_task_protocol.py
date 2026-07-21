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
from agent_runtime.brain.mission_contract import build_mission_contract
from agent_runtime.run_task import app, _init_agents_for_request, _init_templates_for_agents
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
    assert packet["routing"]["status"] == "capability_mismatch"
    assert packet["routing"]["selected"] is None
    assert {"generate_image", "create_spreadsheet"}.issubset(
        set(packet["required_capabilities"])
    )
    assert "validate_artifact_contract" in packet["required_capabilities"]


def test_provider_router_honors_preferred_provider():
    route = route_artifact_provider(
        ROOT,
        "text",
        preferred_provider="qwen_cli",
    )

    assert route["status"] == "routed"
    assert route["selected"]["provider_id"] == "qwen_cli"
    assert route["selected"]["worker"] == "qwen"


def test_text_artifact_contract_preserves_explicit_yaml_format():
    packet = build_artifact_task_contract(
        ROOT,
        "Create the machine artifact as fact_distillation.yml in YAML format.",
        artifact_type="text",
        output_path="projects/AgentLab/runs/task_yaml/artifacts/fact_distillation.yml",
        project="AgentLab",
        task_id="task_yaml",
    )

    assert packet["output"]["format"] == "yaml"
    assert packet["routing"]["status"] == "routed"
    assert packet["routing"]["selected"]["provider_id"] == "qwen_cli"


def test_yaml_artifact_can_prefer_native_codex_cli():
    packet = build_artifact_task_contract(
        ROOT,
        "Create fact_distillation.yml as machine-readable YAML.",
        artifact_type="text",
        output_path="projects/AgentLab/runs/task_yaml/artifacts/fact_distillation.yml",
        project="AgentLab",
        task_id="task_yaml",
        preferred_provider="codex_cli",
    )

    assert packet["output"]["format"] == "yaml"
    assert packet["routing"]["status"] == "routed"
    assert packet["routing"]["selected"] == {
        "provider_id": "codex_cli",
        "worker": "codex",
        "priority": 90,
        "fallback": False,
        "reason": "codex_cli handles text with required capabilities",
    }


def test_media_artifact_routes_to_grok_producer():
    route = route_artifact_provider(ROOT, "image")

    assert route["status"] == "routed"
    assert route["selected"]["provider_id"] == "grok_media"
    assert route["selected"]["worker"] == "grok"


def test_audio_artifact_fails_closed_without_a_capable_provider():
    route = route_artifact_provider(ROOT, "audio")

    assert route["status"] == "capability_mismatch"
    assert route["selected"] is None
    assert route["candidates"] == []


def test_incompatible_preferred_provider_does_not_silently_switch():
    route = route_artifact_provider(
        ROOT,
        "image",
        preferred_provider="qwen_cli",
    )

    assert route["status"] == "capability_mismatch"
    assert route["selected"] is None
    assert route["candidates"] == []


def test_pure_artifact_request_routes_to_artifact_producer_not_coder():
    route = recommend_route("请生成一份 markdown 报告和一张 png 图片")

    assert "ArtifactProducer" in route.agents
    assert "Coder" not in route.agents
    assert route.route_key == "artifact_production_task"


def test_single_media_output_routes_to_media_acceptance_pipeline():
    for request in ("Generate an image.png", "Create a video.mp4"):
        route = recommend_route(request)
        assert route.route_key == "media_generation_task"
        assert {"ArtifactProducer", "Observer", "Reviewer", "Verifier"}.issubset(
            set(route.agents)
        )


def test_image_plus_video_contract_is_mixed_instead_of_silently_partial():
    contract = build_mission_contract(
        "Generate an image.png and a video.mp4.",
        project_id="AgentLab",
        task_id="task_mixed_media",
        agentlab_root=ROOT,
    )

    assert contract["artifact_components"] == ["image", "video"]
    media = contract["media_generation_contract"]
    assert media["modality"] == "mixed"
    assert media["executable"] is False
    assert media["selected_backend"] != "hermes_grok_oauth"


def test_mixed_code_and_artifact_request_routes_to_both():
    route = recommend_route("实现导出功能，并生成一个 xlsx 表格样例")

    assert "Coder" in route.agents
    assert "ArtifactProducer" in route.agents
    assert route.agents.index("Coder") < route.agents.index("ArtifactProducer")


def test_artifact_producer_role_session_includes_contract_status():
    packet = build_role_session(ROOT, "ArtifactProducer", "grok", project="AgentLab", task_id="task_missing")

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


def test_init_task_media_request_uses_artifact_shell_not_code_shell():
    prompt = "把 Crown of Ash 第一卷做成连续漫画、短视频和海报图册，需要保持角色视觉、场景资产和镜头连续性。"

    agents, route_key = _init_agents_for_request(
        prompt,
        agentlab_root=ROOT,
        project_name="Crown_of_Ash",
        task_id="task_init_media",
    )
    templates = _init_templates_for_agents(prompt, agents)

    assert route_key == "media_generation_task"
    assert "ArtifactProducer" in agents
    assert "Coder" not in agents
    assert "artifact_producer_report.md" in templates
    assert "06_implementation_report.md" not in templates
    assert "05_coder_prompt.md" not in templates


def test_init_task_narrative_request_uses_writer_shell_not_code_shell():
    prompt = "写 Crown 第 1 章。"

    agents, route_key = _init_agents_for_request(
        prompt,
        agentlab_root=ROOT,
        project_name="Crown_of_Ash",
        task_id="task_init_narrative",
    )
    templates = _init_templates_for_agents(prompt, agents)

    assert route_key == "narrative_light_chapter"
    assert agents == ["Supervisor", "Writer"]
    assert "fiction_draft.md" in templates
    assert "06_implementation_report.md" not in templates


def test_init_task_article_request_uses_article_shell_not_code_shell():
    prompt = "写一篇产品说明文章，介绍 AgentLab 的轻量写作路径。"

    agents, route_key = _init_agents_for_request(
        prompt,
        agentlab_root=ROOT,
        project_name="AgentLab",
        task_id="task_init_article",
    )
    templates = _init_templates_for_agents(prompt, agents)

    assert route_key == "article_light_draft"
    assert agents == ["Supervisor", "ArtifactProducer"]
    assert "artifact_producer_report.md" in templates
    assert "06_implementation_report.md" not in templates


def test_init_task_code_request_keeps_implementation_shell():
    prompt = "Implement a small production repository code change, update tests, and record the implementation report."

    agents, route_key = _init_agents_for_request(
        prompt,
        agentlab_root=ROOT,
        project_name="AgentLab",
        task_id="task_init_code",
    )
    templates = _init_templates_for_agents(prompt, agents)

    assert route_key
    assert "Coder" in agents
    assert "06_implementation_report.md" in templates
    assert "05_coder_prompt.md" in templates


def test_init_templates_do_not_expand_a_small_code_route_to_legacy_full_chain():
    templates = _init_templates_for_agents(
        "Fix one file and run its focused test.",
        ["Supervisor", "Coder", "TesterAuditor"],
    )

    assert "05_coder_prompt.md" in templates
    assert "07_validation_report.md" in templates
    assert "02_reposcout_report.md" not in templates
    assert "03_research_notes.md" not in templates
    assert "04_interface_map.md" not in templates
    assert "09_archive_update.md" not in templates


def test_blank_init_request_stays_unclassified_and_supervisor_only():
    agents, route_key = _init_agents_for_request(
        "# User Request\n\nDescribe the task here.",
        agentlab_root=ROOT,
        project_name="AgentLab",
        task_id="task_blank_init",
    )

    assert route_key == "unclassified_blank_request"
    assert agents == ["Supervisor"]
    assert set(_init_templates_for_agents("", agents)) == {
        "user_request.md",
        "01_supervisor_plan.md",
        "cost_ledger.yml",
        "brain_decisions.yml",
    }
