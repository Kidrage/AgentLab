from __future__ import annotations

from pathlib import Path

import yaml

from agent_runtime.narrative.production.brief_compiler import compile_creative_brief
from agent_runtime.narrative.longform_governance import (
    build_crown_planning_skeleton,
    validate_chapter_contract,
    validate_chapter_contract_graph,
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
        "character_intent_gate": {
            "focal_character": "char_kain",
            "knowledge_before": "只知道灰痕曾自行回应触碰，不知道它能否受控或需要付出什么",
            "emotional_state_before": "恐惧被教会发现，仍把异常视为必须藏住的威胁",
            "behavioral_tendency": "优先隐瞒、观察和维持生计，不主动追求力量",
            "risk_tolerance": "low",
            "intended_action": "先隔离灰样并观察它是否再次自行变化",
            "action_trigger": "巡查名单提前出现他的名字，且熔炉故障会使他失去唯一收入",
            "credible_transition": "外部生存压力迫使他从被动观察升级到一次最小、可中止的验证",
            "forbidden_author_knowledge_shortcuts": [
                "不得把未知灰痕当作可枚举技能",
                "不得在没有新证据时系统测试能力边界",
            ],
        },
        "must_not_repeat": [
            "不得重复已经完成的灰痕首次响应场景",
        ],
        "forbidden_facts": [
            "师父已经死亡",
            "凯恩背负教会税债",
        ],
        "fact_invention_policy": {
            "absent_fact_rule": "未在密封证据中出现的持久事实保持未知，不得补写为既成事实",
            "allowed_scene_texture": [
                "不产生后续约束的感官细节",
                "不具名且不改变世界规则的临时物件",
            ],
            "forbidden_persistent_fact_classes": [
                "新人物身世或既往事件",
                "新制度、税制、法令或超凡分类",
                "会跨章持续的债务、资源、关系或藏匿点",
            ],
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
            "tier": position,
            "disturbance_or_pressure": "教会巡查名单提前出现凯恩的名字",
            "personal_stakes": "他的铁匠身份和行动自由同时受到威胁",
            "next_required_action": "必须在天亮前决定逃离还是伪造检测结果",
            "reader_question": "是谁在凯恩觉醒前就把他写进了名单？",
            "irreversible_change": "凯恩从未登记者变为教会的具名目标",
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
    assert bundle["dependency_inventory"] == []
    assert bundle["world_state_baseline"] == {}
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


def test_character_intent_gate_blocks_author_knowledge_and_unearned_experimentation() -> None:
    contract = _chapter_contract()
    assert validate_chapter_contract(contract) == []

    gate = contract["character_intent_gate"]
    gate["knowledge_before"] = ""
    gate["risk_tolerance"] = "reckless"
    gate["action_trigger"] = "what_happens_next"
    gate["forbidden_author_knowledge_shortcuts"] = []

    issues = validate_chapter_contract(contract)

    assert "missing:character_intent_gate.knowledge_before" in issues
    assert "invalid:character_intent_gate.risk_tolerance" in issues
    assert "placeholder:character_intent_gate.action_trigger" in issues
    assert (
        "invalid:character_intent_gate.forbidden_author_knowledge_shortcuts"
        in issues
    )


def test_v3_contract_requires_explicit_negative_story_constraints() -> None:
    contract = _chapter_contract()
    assert validate_chapter_contract(contract) == []

    contract["must_not_repeat"] = []
    contract["forbidden_facts"] = ["", 7]

    issues = validate_chapter_contract(contract)

    assert "invalid:must_not_repeat" in issues
    assert "invalid:forbidden_facts" in issues


def test_v3_contract_requires_explicit_fact_invention_boundary() -> None:
    contract = _chapter_contract()
    contract["fact_invention_policy"]["allowed_scene_texture"] = []
    contract["fact_invention_policy"]["absent_fact_rule"] = ""

    issues = validate_chapter_contract(contract)

    assert "missing:fact_invention_policy.absent_fact_rule" in issues
    assert "invalid:fact_invention_policy.allowed_scene_texture" in issues


def test_regular_hook_accepts_relationship_tension_but_not_generic_question() -> None:
    contract = _chapter_contract(chapter=27, position="regular")
    contract["hook_contract"] = {
        "tier": "regular",
        "disturbance_or_pressure": "阿德里安拒绝解释七年前的来历",
        "personal_stakes": "凯恩必须决定是否继续信任唯一的导师",
        "next_required_action": "凯恩将独自核对被涂改的名册",
        "reader_question": "名册里被刮掉的第二个名字属于谁？",
    }
    assert validate_chapter_contract(contract) == []

    contract["hook_contract"]["reader_question"] = "what_happens_next"
    assert "placeholder:hook_contract.reader_question" in validate_chapter_contract(contract)


def test_boundary_chapters_cannot_downgrade_their_hook_tier() -> None:
    contract = _chapter_contract(chapter=650, position="regular")
    contract["hook_contract"]["tier"] = "regular"

    issues = validate_chapter_contract(contract)

    assert "invalid:chapter_position.expected_volume_close" in issues


def test_non_boundary_chapters_cannot_claim_open_or_close_hook_tiers() -> None:
    contract = _chapter_contract(chapter=27, position="volume_open")
    contract["hook_contract"]["tier"] = "volume_open"

    assert "invalid:chapter_position.reserved_for_boundary" in (
        validate_chapter_contract(contract)
    )


def test_optional_state_sections_require_explicit_absence_reasons() -> None:
    contract = _chapter_contract(chapter=27, position="regular")
    contract["hook_contract"].pop("irreversible_change")
    contract["supporting_actor_states"] = []
    contract["foreshadow_actions"] = []
    contract["world_state_delta"] = None

    issues = validate_chapter_contract(contract)

    assert "missing:contract.supporting_actor_absence_reason" in issues
    assert "missing:contract.foreshadow_absence_reason" in issues
    assert "missing:contract.world_state_no_change_reason" in issues

    contract.update(
        supporting_actor_absence_reason="本章为凯恩独处验证，无重要配角在场或幕后行动",
        foreshadow_absence_reason="本章只推进已登记因果，不新增或触碰伏笔",
        world_state_no_change_reason="变化局限于凯恩的认知，公共世界状态保持不变",
    )
    assert validate_chapter_contract(contract) == []


def test_contract_graph_tracks_foreshadow_windows_and_world_axis_continuity() -> None:
    first = _chapter_contract(chapter=27, position="regular")
    first["hook_contract"].pop("irreversible_change")
    first["foreshadow_actions"][0]["target_window"] = [28, 30]
    second = _chapter_contract(chapter=28, position="regular")
    second["hook_contract"].pop("irreversible_change")
    second["foreshadow_actions"][0]["action"] = "develop"
    second["world_state_delta"]["before"] = "不连续的旧状态"

    issues = validate_chapter_contract_graph([first, second])

    assert issues == ["chapter:28:world_chain_mismatch:church_surveillance"]

    second["world_state_delta"]["before"] = first["world_state_delta"]["after"]
    assert validate_chapter_contract_graph([first, second]) == []


def test_contract_graph_anchors_dependencies_and_first_world_state() -> None:
    contract = _chapter_contract(chapter=27, position="regular")
    contract["hook_contract"].pop("irreversible_change")

    assert validate_chapter_contract_graph(
        [contract],
        known_dependencies={"faction_church"},
        world_state_baseline={
            "church_surveillance": "灰谷只接受季节性抽查"
        },
    ) == [
        "chapter:27:foreshadow:fs_preprinted_name:target_not_touched"
    ]

    contract["foreshadow_actions"][0]["dependencies"] = ["unknown_faction"]
    contract["world_state_delta"]["before"] = "没有经过审计的状态"
    issues = validate_chapter_contract_graph(
        [contract],
        known_dependencies={"faction_church"},
        world_state_baseline={
            "church_surveillance": "灰谷只接受季节性抽查"
        },
    )

    assert (
        "chapter:27:foreshadow:fs_preprinted_name:unknown_dependency:unknown_faction"
        in issues
    )
    assert "chapter:27:world_baseline_mismatch:church_surveillance" in issues


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
    assert brief["chapter_contract"]["character_intent_gate"]["risk_tolerance"] == "low"
    assert brief["must_not_repeat"] == [
        "不得重复已经完成的灰痕首次响应场景"
    ]
    assert brief["forbidden_facts"] == [
        "师父已经死亡",
        "凯恩背负教会税债",
    ]
    assert brief["fact_invention_policy"]["absent_fact_rule"].startswith(
        "未在密封证据中出现"
    )
    assert brief["must_preserve"] == []
    assert "验证灰痕" in brief["opposing_wants"]
    assert brief["reader_question"] == "是谁在凯恩觉醒前就把他写进了名单？"
