from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent_runtime"))

from workflow_plan import build_workflow_plan


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


def test_code_workflow_plan_keeps_implementation_gate(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    request = tmp_path / "user_request.md"
    request.write_text(
        "Implement a small repository code change, update tests, and record the implementation report.",
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
    assert "implementation_report" in gate_ids


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
    gate_ids = {gate["id"] for gate in plan.validation_gates}
    assert {"article_draft", "article_structure_check"} <= gate_ids
