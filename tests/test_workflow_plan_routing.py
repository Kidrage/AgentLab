from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from lifecycle_graph import create_lifecycle
from production_packs import build_production_pack
from schemas import AgentRoute
from workflow_plan import _route_for_production_pack
from workflow_plan import build_workflow_plan


def _included_required_io(plan) -> list[str]:
    return [
        str(item)
        for config in plan.included_agents.values()
        for item in (config.get("required_inputs", []) + config.get("required_outputs", []))
    ]


def _assert_no_code_shell_contract(plan) -> None:
    required_io = _included_required_io(plan)
    assert not any("implementation_report" in item for item in required_io)
    assert not any("interface_map" in item for item in required_io)
    assert not any("05_coder_prompt" in item for item in required_io)
    assert not any("01_REPO_MAP" in item for item in required_io)


def _memory_task_state(plan) -> list[str]:
    return list(plan.memory_policy.get("records", {}).get("task_state", []))


def _assert_no_code_shell_task_state(plan) -> None:
    task_state = _memory_task_state(plan)
    assert not any("implementation_report" in item for item in task_state)
    assert not any("interface_map" in item for item in task_state)
    assert not any("reposcout" in item for item in task_state)
    assert not any("repo_map" in item.lower() for item in task_state)


def _validation_gate_text(plan) -> str:
    return "\n".join(str(gate) for gate in plan.validation_gates).lower()


def _assert_no_code_shell_validation_gate_text(plan) -> None:
    gate_text = _validation_gate_text(plan)
    assert "repo map" not in gate_text
    assert "source write policy" not in gate_text
    assert "implementation_report" not in gate_text


def test_workflow_driver_resolves_the_configured_role_backend_mode(
    tmp_path: Path,
) -> None:
    request = tmp_path / "user_request.md"
    request.write_text(
        "Implement a small production repository code change with tests.",
        encoding="utf-8",
    )

    cli_plan = build_workflow_plan(
        ROOT,
        "AgentLab",
        "task_driver_cli_probe",
        user_request_path=request,
    )
    assert cli_plan.execution_backend == "agentlab_orchestrated_cli"
    assert {profile["resolved_mode"] for profile in cli_plan.model_profiles.values()} == {
        "full_cli"
    }

    for retired_driver in ("api_native", "hybrid_ide", "codex_full_driver"):
        with pytest.raises(ValueError, match="inactive workflow driver"):
            build_workflow_plan(
                ROOT,
                "AgentLab",
                f"task_retired_{retired_driver}_probe",
                execution_backend=retired_driver,
                user_request_path=request,
            )


def test_workflow_plan_uses_mission_route_for_chinese_crown_chapter(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "按照《灰烬王冠》重构蓝图及角色圣经，撰写第10章_小规模追击。"
        "具体情节：第一次小规模冲突。",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_crown_rewrite_ch10",
        user_request_path=request,
    )

    assert plan.route.route_key == "narrative_light_chapter"
    assert plan.route.agents == ["Supervisor", "Writer"]
    assert plan.production_pack["pack_id"] == "narrative_longform"
    assert "project_fact_snapshot" in plan.production_pack["memory_contract"]
    assert "CODER_IMPLEMENTATION" not in plan.production_pack["lifecycle_nodes"]
    assert plan.artifact_intent["production_dir"].endswith("projects/Crown_of_Ash/production/manuscript")
    gate_ids = {gate["id"] for gate in plan.validation_gates}
    gate_owners = {gate["owner"] for gate in plan.validation_gates}
    assert "implementation_report" not in gate_ids
    assert "validation_evidence" not in gate_ids
    assert {
        "fiction_draft",
        "continuity_ledger",
        "state_transition_proposal",
        "narrative_delivery_receipt",
    } <= gate_ids
    assert gate_owners <= set(plan.route.agents)

    required_inputs = [
        item
        for config in plan.included_agents.values()
        for item in config.get("required_inputs", [])
    ]
    assert not any("implementation_report" in item for item in required_inputs)
    assert not any("interface_map" in item for item in required_inputs)
    assert "runs/task_xxxx/chapter_packet.yml" in plan.included_agents["Writer"]["required_inputs"]
    assert "runs/task_xxxx/state_transition_proposal.yml" in plan.included_agents["Writer"]["required_outputs"]
    _assert_no_code_shell_task_state(plan)
    assert {
        "chapter_packet.yml",
        "fiction_draft.md",
        "continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_delivery_receipt.yml",
    } <= set(_memory_task_state(plan))


def test_code_workflow_plan_keeps_implementation_gate(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "Implement a small production repository code change, update tests, and record the implementation report.",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_code_route_probe",
        user_request_path=request,
    )

    gate_ids = {gate["id"] for gate in plan.validation_gates}
    assert plan.route.route_key != "narrative_light_chapter"
    assert plan.production_pack["pack_id"] == "code_factory"
    assert "CODER_IMPLEMENTATION" in plan.production_pack["lifecycle_nodes"]
    assert "ARTIFACT_PRODUCTION" in plan.production_pack["lifecycle_nodes"]
    assert "implementation_report" in gate_ids
    required_io = _included_required_io(plan)
    assert any("implementation_report" in item for item in required_io)
    assert {"implementation_report.md", "reposcout_report.md"} <= set(_memory_task_state(plan))
    assert "repo map" in _validation_gate_text(plan)
    assert "source write policy" in _validation_gate_text(plan)


def test_explicit_frugal_budget_is_not_upgraded_for_r2_code_task(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "Implement a small production repository code change, update tests, and record the implementation report.",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        root,
        "AgentLab",
        "task_code_frugal_probe",
        user_request_path=request,
        budget_mode="frugal",
    )

    assert plan.risk_level == "R2"
    assert plan.budget_mode == "frugal"
    assert plan.production_pack["pack_id"] == "code_factory"


def test_workflow_plan_routes_narrative_audit_to_heavy_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text("审计 Crown_of_Ash 前 10 章，检查连续性并给出 promotion 前验收结论。", encoding="utf-8")

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_crown_audit_ch01_ch10",
        user_request_path=request,
    )

    assert plan.route.route_key == "narrative_heavy_audit"
    assert plan.route.agents == ["Supervisor", "Reviewer", "Scribe", "Verifier"]
    gate_ids = {gate["id"] for gate in plan.validation_gates}
    assert {
        "fiction_review",
        "continuity_failure_report",
        "state_transition_proposal",
        "revision_or_rewrite_proposal",
    } <= gate_ids
    _assert_no_code_shell_task_state(plan)
    assert {
        "fiction_draft.md",
        "continuity_ledger.yml",
        "fiction_review.yml",
        "continuity_failure_report.yml",
        "revision_or_rewrite_proposal.yml",
    } <= set(_memory_task_state(plan))


def test_workflow_plan_routes_blocking_rewrite_to_narrative_planner(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "根据 heavy audit 的 blocking findings 重写 Crown_of_Ash 第1章到第200章规划。",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_crown_rewrite_plan_ch001_ch200",
        user_request_path=request,
    )

    assert plan.route.route_key == "narrative_rewrite_plan"
    assert plan.route.agents == ["Supervisor", "NarrativePlanner"]
    assert plan.production_pack["pack_id"] == "narrative_longform"
    assert [
        (gate["id"], gate["owner"], gate["evidence"])
        for gate in plan.validation_gates
    ] == [("chapter_state_plan", "NarrativePlanner", ["chapter_state_plan.yml"])]
    planner = plan.included_agents["NarrativePlanner"]
    assert planner["required_outputs"] == ["runs/task_xxxx/chapter_state_plan.yml"]
    planner_execution = plan.model_profiles["NarrativePlanner"]
    assert planner_execution["cli_agent"] == "agy"
    assert planner_execution["invocation_contract"] == "agy_narrative_planner"
    assert {
        "narrative_rewrite_contract.yml",
        "chapter_state_plan.yml",
        "narrative_planner_validation.yml",
    } <= set(_memory_task_state(plan))
    _assert_no_code_shell_contract(plan)
    _assert_no_code_shell_task_state(plan)


def test_workflow_plan_routes_chapter_range_to_narrative_batch_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text("生成 Crown_of_Ash 第1章到第20章候选稿，保持1500章规模下的时间线一致。", encoding="utf-8")

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_crown_batch_ch01_ch20",
        user_request_path=request,
    )

    assert plan.route.route_key == "narrative_batch_chapters"
    assert plan.route.agents == ["Supervisor", "Writer"]
    assert plan.production_pack["pack_id"] == "narrative_longform"
    writer_outputs = set(plan.included_agents["Writer"]["required_outputs"])
    assert "runs/task_xxxx/chapter_batch_plan.yml" in writer_outputs
    assert "runs/task_xxxx/chapters/" in writer_outputs
    assert "runs/task_xxxx/batch_continuity_ledger.yml" in writer_outputs
    _assert_no_code_shell_task_state(plan)
    assert {
        "chapter_batch_plan.yml",
        "chapters/",
        "batch_continuity_ledger.yml",
        "state_transition_proposal.yml",
        "narrative_batch_delivery_receipt.yml",
    } <= set(_memory_task_state(plan))
    gate_ids = {gate["id"] for gate in plan.validation_gates}
    assert {
        "chapter_batch_plan",
        "chapters",
        "batch_continuity_ledger",
        "state_transition_proposal",
        "narrative_batch_delivery_receipt",
    } <= gate_ids


def test_workflow_plan_routes_plain_article_to_article_light_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text("写一篇产品说明文章，介绍 AgentLab 的轻量写作路径。", encoding="utf-8")

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_article_light",
        user_request_path=request,
    )

    assert plan.route.route_key == "article_light_draft"
    assert plan.route.agents == ["Supervisor", "ArtifactProducer"]
    assert plan.production_pack["pack_id"] == "article_light"
    assert plan.artifact_intent["production_dir"].endswith("projects/Crown_of_Ash/production/artifacts")
    assert "ARTIFACT_PRODUCTION" in plan.production_pack["lifecycle_nodes"]
    assert "article_structure_check" in plan.production_pack["quality_gates"]
    gate_ids = {gate["id"] for gate in plan.validation_gates}
    assert {"article_draft", "article_structure_check"} <= gate_ids
    _assert_no_code_shell_contract(plan)
    _assert_no_code_shell_task_state(plan)
    assert {"article_draft.md", "article_structure_check.yml"} <= set(_memory_task_state(plan))


def test_artifact_route_has_explicit_artifact_producer_budget(tmp_path: Path) -> None:
    request = tmp_path / "user_request.md"
    request.write_text(
        "生成一份 YAML 报告和一个交付回执。",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        ROOT,
        "Crown_of_Ash",
        "task_fact_distillation",
        user_request_path=request,
    )

    assert plan.route.route_key == "artifact_production_task"
    producer_budgets = [
        budget for budget in plan.token_budgets if "ArtifactProducer" in budget.phase
    ]
    assert len(producer_budgets) == 1
    assert producer_budgets[0].estimated_input_tokens == 50000
    assert producer_budgets[0].estimated_output_tokens == 16000


def test_workflow_plan_routes_video_series_to_media_series_pack(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "根据 Crown of Ash 剧本制作连续剧短视频，保持角色视觉、镜头、场景资产和集间连续性。",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_crown_media_series",
        user_request_path=request,
    )

    assert plan.route.route_key == "media_generation_task"
    assert "Archivist" not in plan.route.agents
    assert plan.production_pack["pack_id"] == "media_series_production"
    assert plan.artifact_intent["production_dir"].endswith("projects/Crown_of_Ash/production/media")
    assert "character_visual_bible" in plan.production_pack["memory_contract"]
    assert "shot_ledger" in plan.production_pack["memory_contract"]
    assert "ARTIFACT_PRODUCTION" in plan.production_pack["lifecycle_nodes"]
    assert "CODER_IMPLEMENTATION" not in plan.production_pack["lifecycle_nodes"]
    assert "ARCHIVE" not in plan.production_pack["lifecycle_nodes"]
    assert {
        "episode_plan.yml",
        "shot_list.yml",
        "asset_registry.yml",
        "prompt_pack.yml",
        "generation_ledger.yml",
        "media_continuity_ledger.yml",
        "media_qc_report.yml",
    } <= set(plan.production_pack["required_outputs"])

    artifact_outputs = set(plan.included_agents["ArtifactProducer"]["required_outputs"])
    assert "runs/task_xxxx/episode_plan.yml" in artifact_outputs
    assert "runs/task_xxxx/shot_list.yml" in artifact_outputs
    assert "runs/task_xxxx/prompt_pack.yml" in artifact_outputs

    gate_ids = {gate["id"] for gate in plan.validation_gates}
    gate_owners = {gate["owner"] for gate in plan.validation_gates}
    assert "implementation_report" not in gate_ids
    assert {"episode_plan", "shot_list", "prompt_pack", "generation_ledger"} <= gate_ids
    assert "ArtifactProducer" in gate_owners
    _assert_no_code_shell_contract(plan)
    _assert_no_code_shell_task_state(plan)
    _assert_no_code_shell_validation_gate_text(plan)
    assert {
        "episode_plan.yml",
        "shot_list.yml",
        "character_visual_bible.yml",
        "asset_registry.yml",
        "prompt_pack.yml",
        "generation_ledger.yml",
        "media_continuity_ledger.yml",
        "media_qc_report.yml",
        "narrative_media_delivery_receipt.yml",
        "validation_report.md",
        "audit_report.md",
        "verification_report.md",
    } <= set(_memory_task_state(plan))
    assert "Archivist" not in plan.included_agents
    verifier_inputs = set(plan.included_agents["Verifier"]["required_inputs"])
    assert "runs/task_xxxx/episode_plan.yml" in verifier_inputs
    assert "runs/task_xxxx/media_qc_report.yml" in verifier_inputs


def test_unknown_non_code_domain_enters_executable_pack_synthesis_candidate(tmp_path: Path) -> None:
    route = AgentRoute(
        task_size="medium",
        agents=["Supervisor"],
        route_key="immersive_installation_task",
        rationale=["Synthetic route for an unconfigured non-code domain."],
    )
    mission = {
        "project_type": "immersive_installation_project",
        "task_domain": "installation_art",
        "artifact_type": "show_control_package",
    }
    catalog = {
        "core_runtime": ["task_run_state", "artifact_contract", "memory_policy"],
        "pack_synthesis_policy": {
            "enabled": True,
            "agents": ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"],
            "required_outputs": [
                "production_pack_proposal.yml",
                "domain_memory_contract.yml",
                "lifecycle_profile.yml",
            ],
        },
        "packs": [],
    }

    pack = build_production_pack(tmp_path, mission, route, {"production_packs": catalog})
    expanded_route = _route_for_production_pack(route, pack)
    lifecycle = create_lifecycle(
        tmp_path,
        {
            "route": expanded_route.model_dump(mode="json"),
            "production_pack": pack,
        },
    )

    assert pack["status"] == "synthesis_candidate"
    assert pack["required_outputs"] == [
        "production_pack_proposal.yml",
        "domain_memory_contract.yml",
        "lifecycle_profile.yml",
    ]
    assert pack["agents"][:4] == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    assert expanded_route.agents[:4] == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    assert "Researcher" in expanded_route.agents
    assert "ArtifactProducer" in expanded_route.agents
    assert "Verifier" in expanded_route.agents
    assert "RESEARCH_OPTIONAL" in pack["lifecycle_nodes"]
    assert "domain_research_brief" in pack["memory_contract"]
    assert "domain_research_brief" in pack["quality_gates"]
    assert lifecycle["nodes"]["RESEARCH_OPTIONAL"]["status"] == "waiting"
    assert lifecycle["nodes"]["ARTIFACT_PRODUCTION"]["status"] == "waiting"
    assert lifecycle["nodes"]["VERIFY"]["status"] == "waiting"
    assert lifecycle["nodes"]["CODER_IMPLEMENTATION"]["status"] == "skipped"


def test_workflow_plan_synthesizes_pack_for_unconfigured_multimodal_installation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "建立一个沉浸式展览生成系统，需要长期维护空间装置、灯光Cue、声音Cue、角色引导词和每次展演状态。",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        root,
        "AgentLab",
        "task_installation_pack_synthesis",
        user_request_path=request,
    )

    assert plan.production_pack["status"] == "synthesis_candidate"
    assert plan.production_pack["pack_id"] == "pack_synthesis_candidate"
    assert plan.mission_contract["task_id"] == "task_installation_pack_synthesis"
    assert plan.mission_contract["compiler_source"] == "rule_based"
    assert plan.mission_contract["route_decision"]["selected_route"] == (
        plan.route.route_key
    )
    assert "mission_contract" not in plan.model_dump(mode="json")
    assert plan.artifact_intent["production_dir"].endswith("projects/AgentLab/production/artifacts")
    assert plan.production_pack["task_domain"] == "multimodal_asset_generation"
    assert "Coder" not in plan.route.agents
    assert plan.route.agents[:4] == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    assert "Researcher" in plan.route.agents
    assert "ArtifactProducer" in plan.route.agents
    assert "Verifier" in plan.route.agents
    _assert_no_code_shell_contract(plan)
    _assert_no_code_shell_task_state(plan)
    _assert_no_code_shell_validation_gate_text(plan)
    verifier_inputs = set(plan.included_agents["Verifier"]["required_inputs"])
    artifact_inputs = set(plan.included_agents["ArtifactProducer"]["required_inputs"])
    researcher_outputs = set(plan.included_agents["Researcher"]["required_outputs"])
    assert "runs/task_xxxx/domain_research_brief.md" in artifact_inputs
    assert "runs/task_xxxx/domain_research_brief.md" in verifier_inputs
    assert "runs/task_xxxx/domain_research_brief.md" in researcher_outputs
    assert "runs/task_xxxx/production_pack_proposal.yml" in verifier_inputs
    assert "runs/task_xxxx/domain_memory_contract.yml" in verifier_inputs
    assert {
        "production_pack_proposal.yml",
        "domain_memory_contract.yml",
        "lifecycle_profile.yml",
    } <= set(plan.production_pack["required_outputs"])
    assert "domain_research_brief.md" in set(_memory_task_state(plan))
    assert "domain_research_brief" in {gate["id"] for gate in plan.validation_gates}


def test_workflow_plan_synthesizes_pack_for_unconfigured_audio_installation(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "为一个长期互动音频装置项目设计生成链路，需要持续维护声音角色、参数账本、场景状态和多轮渲染验收。",
        encoding="utf-8",
    )

    plan = build_workflow_plan(
        root,
        "AgentLab",
        "task_audio_pack_synthesis",
        user_request_path=request,
    )

    assert plan.production_pack["status"] == "synthesis_candidate"
    assert plan.production_pack["task_domain"] == "audio_dsp_experiment"
    assert "Coder" not in plan.route.agents
    assert plan.route.agents == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    _assert_no_code_shell_contract(plan)
    _assert_no_code_shell_task_state(plan)
    _assert_no_code_shell_validation_gate_text(plan)
    assert {
        "production_pack_proposal.yml",
        "domain_memory_contract.yml",
        "lifecycle_profile.yml",
    } <= set(_memory_task_state(plan))


def test_workflow_plan_synthesizes_pack_for_explicit_pack_design_request(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text("为一个未知领域任务创建生产包并准备生命周期与记忆合约。", encoding="utf-8")

    plan = build_workflow_plan(
        root,
        "AgentLab",
        "task_explicit_pack_synthesis",
        user_request_path=request,
    )

    assert plan.route.route_key == "artifact_production_task"
    assert plan.production_pack["status"] == "synthesis_candidate"
    assert plan.production_pack["pack_id"] == "pack_synthesis_candidate"
    assert plan.production_pack["task_domain"] == "production_pack_synthesis"
    assert plan.production_pack["artifact_type"] == "production_pack_candidate"
    assert plan.route.agents == ["Supervisor", "Researcher", "ArtifactProducer", "Verifier"]
    assert "Coder" not in plan.route.agents
    _assert_no_code_shell_contract(plan)
    _assert_no_code_shell_task_state(plan)
    _assert_no_code_shell_validation_gate_text(plan)
    assert {
        "domain_research_brief.md",
        "production_pack_proposal.yml",
        "domain_memory_contract.yml",
        "lifecycle_profile.yml",
    } <= set(_memory_task_state(plan))


def test_simple_markdown_report_uses_generic_artifact_pack_not_synthesis(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text("生成一份 markdown 报告和一个交付回执。", encoding="utf-8")

    plan = build_workflow_plan(
        root,
        "AgentLab",
        "task_simple_markdown_report",
        user_request_path=request,
    )

    assert plan.route.route_key == "artifact_production_task"
    assert plan.production_pack["status"] == "configured"
    assert plan.production_pack["pack_id"] == "generic_artifact"
    assert "Coder" not in plan.route.agents
    _assert_no_code_shell_contract(plan)
    _assert_no_code_shell_task_state(plan)
    _assert_no_code_shell_validation_gate_text(plan)
    assert {"artifact_producer_report.md", "delivery_receipt.yml"} <= set(_memory_task_state(plan))


def test_workflow_plan_keeps_fiction_market_article_out_of_narrative_path(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text("写一篇关于小说市场的分析文章。", encoding="utf-8")

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_fiction_market_article",
        user_request_path=request,
    )

    assert plan.route.route_key == "article_light_draft"
    assert "Writer" not in plan.route.agents
    _assert_no_code_shell_task_state(plan)


def test_workflow_plan_routes_short_chapter_check_to_heavy_audit(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text("检查前10章连续性。", encoding="utf-8")

    plan = build_workflow_plan(
        root,
        "Crown_of_Ash",
        "task_short_continuity_check",
        user_request_path=request,
    )

    assert plan.route.route_key == "narrative_heavy_audit"
    assert plan.route.agents == ["Supervisor", "Reviewer", "Scribe", "Verifier"]
    _assert_no_code_shell_task_state(plan)
