from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.narrative.production.brief_compiler import compile_creative_brief
from agent_runtime.narrative.longform_governance import (
    build_crown_planning_skeleton,
    validate_chapter_contract,
    validate_longform_plan_bundle,
)
from agent_runtime.narrative_delivery import validate_chapter_state_plan


def _chapter_contract(chapter: int = 1, position: str = "series_open") -> dict:
    return {
        "schema_version": "chapter-contract/v3",
        "chapter": chapter,
        "chapter_position": position,
        "pov": "char_kain",
        "primary_function": "plot",
        "turn": "凯恩发现灰痕会回应他的锻造判断",
        "cost": "继续隐瞒会使他失去离开灰谷的唯一窗口",
        "protagonist_drive": {
            "long_horizon_desire": "离开灰谷并查清父亲被定罪的真相",
            "volume_goal": "取得能够穿过教会封锁的身份",
            "current_goal": "在巡查前验证灰痕是否受自己控制",
            "self_initiated_move": "主动用三种温度测试灰痕反应",
            "obstacle": "阿德里安隐瞒了灰痕真正的风险",
            "failure_cost": "被认证者登记并失去自由",
            "counterfactual_action": "即使巡查没有发生，他也会完成测试并准备离谷",
            "desire_delta": "从忍耐转为主动调查",
        },
        "supporting_actor_states": [
            {
                "actor_ref": "char_adrian",
                "private_goal": "让凯恩觉醒但不暴露自己的旧身份",
                "fear_or_constraint": "认证者能识别他七年前留下的圣痕",
                "known_information": "灰痕会对锻造温度产生回应",
                "current_plan": "用西坡灰样诱导凯恩自行验证",
                "offscreen_action": "提前转移藏在废井里的教会记录",
                "resource": "一份被涂改的异相者名册",
                "relationship_stance": "保护凯恩但拒绝完整坦白",
                "state_delta": "决定承担一次可追踪的暴露风险",
            }
        ],
        "hook_contract": {
            "disturbance_or_pressure": "教会巡查名单提前出现凯恩的名字",
            "personal_stakes": "他的铁匠身份和行动自由同时受到威胁",
            "next_required_action": "必须在天亮前决定逃离还是伪造检测结果",
            "reader_question": "是谁在凯恩觉醒前就把他写进了名单？",
        },
        "foreshadow_actions": [
            {
                "foreshadow_id": "fs_preprinted_name",
                "action": "seed",
                "target_window": [8, 14],
                "dependencies": ["faction_church"],
                "evidence_target": "名单上的墨迹早于本次巡查",
            }
        ],
        "world_state_delta": {
            "axis": "church_surveillance",
            "before": "灰谷只接受季节性抽查",
            "after": "灰谷进入具名监控",
            "cause": "异常灰样被提前登记",
            "evidence_target": "市场入口出现持名检查",
        },
    }


def test_crown_skeleton_partitions_1980_chapters_into_45_arcs_and_225_windows() -> None:
    bundle = build_crown_planning_skeleton()

    assert bundle["status"] == "candidate"
    assert bundle["candidate_only"] is True
    assert bundle["production_modified"] is False
    assert [volume["chapter_range"] for volume in bundle["volumes"]] == [
        [1, 650],
        [651, 1310],
        [1311, 1980],
    ]
    assert len(bundle["macro_arcs"]) == 45
    assert len(bundle["planning_windows"]) == 225
    assert bundle["macro_arcs"][0]["chapter_range"][0] == 1
    assert bundle["macro_arcs"][-1]["chapter_range"][1] == 1980
    assert validate_longform_plan_bundle(bundle)["status"] == "pass"


def test_chapter_contract_requires_active_desire_and_autonomous_npc() -> None:
    contract = _chapter_contract()
    assert validate_chapter_contract(contract) == []

    contract["protagonist_drive"]["counterfactual_action"] = "what_happens_next"
    contract["supporting_actor_states"][0]["current_plan"] = ""
    issues = validate_chapter_contract(contract)

    assert "placeholder:protagonist_drive.counterfactual_action" in issues
    assert "missing:supporting_actor_states[0].current_plan" in issues


def test_regular_hook_accepts_relationship_tension_but_not_generic_question() -> None:
    contract = _chapter_contract(chapter=27, position="regular")
    contract["hook_contract"] = {
        "disturbance_or_pressure": "阿德里安拒绝解释七年前的来历",
        "personal_stakes": "凯恩必须决定是否继续信任唯一的导师",
        "next_required_action": "凯恩将独自核对被涂改的名册",
        "reader_question": "名册里被刮掉的第二个名字属于谁？",
    }
    assert validate_chapter_contract(contract) == []

    contract["hook_contract"]["reader_question"] = "what_happens_next"
    assert "placeholder:hook_contract.reader_question" in validate_chapter_contract(contract)


def test_v3_plan_uses_existing_delivery_and_brief_compiler_seams(tmp_path: Path) -> None:
    project_root = tmp_path / "Crown_of_Ash"
    project_root.mkdir()
    contract = _chapter_contract()
    plan_path = project_root / "chapter_state_plan_v3.yml"
    plan_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "contract_version": "chapter-contract/v3",
                "project": "Crown_of_Ash",
                "status": "candidate",
                "candidate_only": True,
                "production_modified": False,
                "chapter_range": [1, 1],
                "chapter_state_plan": [contract],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    validation = validate_chapter_state_plan(
        project_root,
        "chapter_state_plan_v3.yml",
        expected_chapters=[1],
    )
    brief = compile_creative_brief(
        contract,
        source_paths=[str(plan_path)],
    ).to_dict()

    assert validation["status"] == "pass"
    assert brief["v1_source"] is False
    assert brief["chapter_position"] == "series_open"
    assert "验证灰痕" in brief["opposing_wants"]
    assert brief["reader_question"] == "是谁在凯恩觉醒前就把他写进了名单？"
