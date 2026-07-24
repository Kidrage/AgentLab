#!/usr/bin/env python3
"""Compile authoritative Crown chapter cards into chapter-contract/v3.

This is intentionally deterministic: it adds governance structure but never
invents prose.  Chapter-specific story decisions remain in the individual
production/chapter_cards/chNNN.yml files.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


ACTORS = {
    1: "char_adrian",
    2: "char_adrian",
    3: "char_alicia",
    4: "faction_church",
    5: "side_parish_archivist",
    6: "char_lia",
    7: "side_gray_valley_survivors",
    8: "char_alicia",
    9: "char_adrian",
    10: "char_ariana",
    11: "char_lia",
    12: "char_kain",
    13: "char_kael",
    14: "char_kain",
    15: "char_kain",
    16: "char_isabella",
    17: "char_kain",
    18: "char_kain",
    19: "char_alicia",
    20: "char_ariana",
    21: "char_serai_nightstripe",
    22: "side_joran_keymonger",
    23: "char_lia",
    24: "char_serai_nightstripe",
    25: "char_alicia",
}

SCENE_GOALS_ZH = {
    1: "在薄暮前完成犁刃、维持铁匠生计；冷灰主动回应旧伤后立刻遮掩异常",
    2: "在无人处借即将熄灭的炉火做一次可中止的最小验证，出现代价便停手",
    3: "在教会彻底封住灰谷出口前穿过集市，同时避免暴露灰痕残留",
    4: "让艾莉希亚先以灰样重建异常过程，再决定该盘问谁",
    5: "在第一轮抓捕前核对教区户籍与隔离名单，找出被人为挖去的姓名",
    6: "在不宣称控制力量的前提下，与印记中的存在沟通并熬过痉挛",
    7: "两套力量都局部失效时，引导被困平民离开裂隙缺口",
    8: "察觉教会要把凯恩当作媒介后，主动脱离押送队伍",
    9: "追问亚德里安的真实来历，同时阻止书记官把救援行为改写为异端罪证",
    10: "借救济车队离开灰谷，并接受一笔边界清楚、可偿还而非人身依附的债",
    11: "用灰痕阻止车队事故，随后逐项确认自己究竟失去了哪段记忆",
    12: "分辨莉娅的碎片记忆与裂隙制造的命令幻觉",
    13: "在内部审查前，将艾莉希亚自己的圣灼伤与没收的灰痕残留进行比对",
    14: "以明确写下的研究条件接近车队，提出有限的稳定方案",
    15: "在书面限用协议下，协助凯恩熬过裂隙潮并记录真实代价",
    16: "揭穿伊莎贝拉暗中的测量，同时保住仍有价值的脆弱同盟",
    17: "在追捕凯恩与守住即将坍塌的平民救济桥之间作出不可撤回的选择",
    18: "解读废弃哨站的旧信号，从三条北上路线中选出唯一可行者",
    19: "从物资损耗推断逃亡者去向，并迫使艾莉希亚的忠诚接受现实检验",
    20: "追兵逼近时决定是否回应远方旧堡仍然亮着的信号",
    21: "穿过向无证旅人收取旧债的北路关卡，弄清门影真正索要的东西",
    22: "换得一把仍记得被北路户籍抹去之房间的钥匙",
    23: "逃离一扇展示“无人死去的灰谷”的空窗，又不粗暴否认其中真实",
    24: "贵族关卡索要隐藏入口时，保住那间没有门的难民客栈",
    25: "在凯尔巡队把私人义务改写成逮捕名单前，理清北路难民网络的欠账",
}


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one mapping")
    return value


def _intent_gate(card: dict[str, Any]) -> dict[str, Any]:
    chapter = int(card["chapter"])
    pov = str(card.get("pov_ref") or card.get("pov") or "char_kain")
    if chapter == 1:
        return {
            "focal_character": pov,
            "knowledge_before": "凯恩只知道灰谷的灰会侵蚀生活，不知道旧伤会回应冷灰",
            "emotional_state_before": "谨慎、疲惫，并把维持铁匠生计置于冒险之前",
            "behavioral_tendency": "先观察、隐瞒异常、保护日常秩序，不主动追求力量",
            "risk_tolerance": "low",
            "intended_action": "藏住冷灰的异常移动并确认没有旁观者",
            "action_trigger": "冷灰逆着气流贴近他的旧伤，且教会认证会夺走他的自由",
            "credible_transition": "异常先主动触碰他；他的第一反应只能是遮掩和最低限度观察",
            "forbidden_author_knowledge_shortcuts": [
                "凯恩只知道教会公开称谓，不得确认自己属于哪类异常，更不得提前知道王冠或灰痕规则",
                "不得把第一次异常写成可操控能力",
            ],
        }
    if chapter == 2:
        return {
            "focal_character": pov,
            "knowledge_before": "凯恩只确认旧伤曾自行发热，不知道它是否受控、会付出何种代价",
            "emotional_state_before": "害怕暴露，也害怕熔炉故障让自己和依赖铁匠铺的人断粮",
            "behavioral_tendency": "优先隐瞒和维持生计，只接受可中止的最小验证",
            "risk_tolerance": "low",
            "intended_action": "在无人处借一次即将熄灭的炉火观察灰痕是否被动回应",
            "action_trigger": "熔炉即将报废、订单违约会立即断绝收入，且异常再次自行升温",
            "credible_transition": "生存压力而非好奇心迫使他做一次最小验证；出现失忆即停止",
            "forbidden_author_knowledge_shortcuts": [
                "不得系统枚举能力、测试上限或设计技能组合",
                "不得使用凯恩尚未获得的魔法术语解释现象",
            ],
        }
    opening = str(card["opening_state"])
    goal = str(card["scene_goal"])
    return {
        "focal_character": pov,
        "knowledge_before": opening,
        "emotional_state_before": f"承受上一章状态的压力，并对“{card['title']}”保持警惕",
        "behavioral_tendency": "依据已知证据采取最小必要行动，先保全同伴与可验证事实",
        "risk_tolerance": "guarded",
        "intended_action": goal,
        "action_trigger": f"上一状态已无法维持；本章压力要求处理：{goal}",
        "credible_transition": "行动由已知压力、既有欲望和可观察证据共同触发，不依赖作者全知",
        "forbidden_author_knowledge_shortcuts": [
            "不得使用角色尚未取得的幕后事实",
            "不得为了展示设定而跳过恐惧、犹豫、代价或证据",
        ],
    }


def _forbidden_facts(chapter: int) -> list[str]:
    if chapter == 1:
        return [
            "老格林",
            "师父已死",
            "师父死了",
            "三天前去世",
            "税债",
            "欠税",
            "税吏",
            "免役文书",
            "十二道栅栏令",
            "铜牌",
            "火刑",
            "预言",
            "源质波动",
            "十二类处置方案",
            "圣印的三种颜色",
            "凯恩见过那些被带走的人",
            "给他这道疤的人",
            "逃亡者",
            "暗格",
            "十二天的干粮",
            "登记官和审判执事已经到了谷口",
            "封锁了南边的石桥",
            "挨家挨户地核对名册",
            "圣光水晶和白色名册",
            "钟声敲响第三遍",
            "第一批教堂执事和巡逻修士",
            "事实上，亚德里安",
        ]
    if chapter == 2:
        return [
            "技能树",
            "能力上限",
            "技能组合",
            "魔力回路",
            "王冠",
            "异相者",
            "灰痕规则",
        ]
    return [
        "本章合同外的新身世",
        "本章合同外的新死亡",
        "本章合同外的新债务",
        "本章合同外的新法令",
        "本章合同外的新预言",
    ]


def _compile(card: dict[str, Any]) -> dict[str, Any]:
    chapter = int(card["chapter"])
    title = str(card["title"])
    pov = str(card.get("pov_ref") or card.get("pov") or "char_kain")
    goal = SCENE_GOALS_ZH.get(chapter, str(card["scene_goal"]))
    turn = str(card["irreversible_plot_change"])
    character_delta = str(card["character_state_change"])
    relation_delta = str(card["relationship_or_worldline_change"])
    foreshadow = str(card["foreshadowing_action"])
    opening = str(card["opening_state"])
    closing = str(card["closing_state"])
    actor = ACTORS.get(chapter, "scene_material_actor")
    position = "series_open" if chapter == 1 else "regular"
    return {
        "schema_version": "chapter-contract/v3",
        "chapter": chapter,
        "chapter_position": position,
        "title": title,
        "volume": "1",
        "phase": str(card.get("phase") or "north_road"),
        "timeline_slot": str(card["timeline_slot"]),
        "pov": pov,
        "primary_function": "plot",
        "turn": turn,
        "cost": f"若失败，{closing}无法成立，并使既有关系代价升级",
        "opening_state": opening,
        "closing_state": closing,
        "protagonist_drive": {
            "long_horizon_desire": "找回被删除的存在证明，并拒绝成为教会、教团或王冠的容器",
            "volume_goal": "沿北路抵达断墙旧堡，取得灰烬印记与被删历史的可验证证据",
            "current_goal": goal,
            "self_initiated_move": goal,
            "obstacle": f"本章的制度、环境或关系压力阻止“{title}”按安全方式完成",
            "failure_cost": f"失去达成“{closing}”的机会，并暴露同伴或关键证据",
            "counterfactual_action": f"即使外部追兵暂缓，角色仍会为“{goal}”采取行动",
            "desire_delta": character_delta,
        },
        "character_intent_gate": _intent_gate(card),
        "supporting_actor_states": [
            {
                "actor_ref": actor,
                "private_goal": f"让“{title}”的结果服务于自己的生存、责任或秘密",
                "fear_or_constraint": "公开真实动机会失去资源、身份或行动自由",
                "known_information": opening,
                "current_plan": f"利用本章场景中的制度或物质条件影响：{goal}",
                "offscreen_action": f"在主视角行动之外准备会改变“{closing}”的资源或证据",
                "resource": "一项与本章地点、职业、档案或交通有关的有限资源",
                "relationship_stance": relation_delta,
                "state_delta": f"因“{turn}”被迫修正下一步计划",
                "pov_visibility_rule": "只允许通过主视角可见的言行、物件和后果表现；不得进入配角内心或直接叙述其幕后盘算",
            }
        ],
        "hook_contract": {
            "tier": position,
            "disturbance_or_pressure": goal,
            "personal_stakes": f"失败会使主视角角色失去自由、同伴、证据或北路窗口：{closing}",
            "next_required_action": f"必须在下一章回应“{turn}”造成的新状态",
            "reader_question": f"“{title}”留下的证据会先被哪一方利用，又会迫使谁改变立场？",
            **(
                {"irreversible_change": turn}
                if position != "regular"
                else {}
            ),
        },
        "foreshadow_actions": [
            {
                "foreshadow_id": f"fs_ch{chapter:03d}_continuity",
                "action": "seed",
                "target_window": [chapter + 1, min(1980, chapter + 20)],
                "dependencies": [],
                "evidence_target": foreshadow,
            }
        ],
        "world_state_delta": {
            "axis": f"chapter_{chapter:03d}_story_state",
            "before": opening,
            "after": closing,
            "cause": turn,
            "evidence_target": relation_delta,
        },
        "must_not_repeat": card.get("forbidden_repeat_patterns")
        or [str(card.get("must_not_repeat") or f"do_not_repeat_chapter_{chapter}")],
        "forbidden_facts": _forbidden_facts(chapter),
        "fact_invention_policy": {
            "absent_fact_rule": "未在密封证据中出现的持久事实保持未知，不得补写为既成事实",
            "allowed_scene_texture": [
                "不产生后续约束的感官细节",
                "不具名且不改变世界规则的临时物件或动作",
                "不改变人物履历、关系或资源状态的市井背景",
            ],
            "forbidden_persistent_fact_classes": [
                "新人物身世、亲缘、死亡、旧伤来源或既往事件",
                "新制度、税制、债务、法令、惩罚程序或超凡分类",
                "精确但无证据的数量、等级、历史年限或组织规则",
                "会跨章持续的关系、资源、藏匿点、承诺或秘密",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--chapter-start", type=int, default=1)
    parser.add_argument("--chapter-end", type=int, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    cards_dir = args.project_root / "production" / "chapter_cards"
    existing_index = _load(cards_dir / "index.yml")
    indexed_entries = {
        int(entry["chapter"]): entry
        for entry in existing_index.get("chapter_state_plan", [])
        if isinstance(entry, dict) and isinstance(entry.get("chapter"), int)
    }
    cards: list[dict[str, Any]] = []
    for chapter in range(args.chapter_start, args.chapter_end + 1):
        card = _load(cards_dir / f"ch{chapter:03d}.yml")
        card = {**indexed_entries.get(chapter, {}), **card}
        cards.append(card)
    contracts = [
        _compile(card)
        for card in cards
    ]
    output = args.out or cards_dir / "index.yml"
    payload = {
        "schema_version": 3,
        "contract_version": "chapter-contract/v3",
        "project": "Crown_of_Ash",
        "status": "candidate",
        "candidate_only": True,
        "production_modified": False,
        "chapter_range": [args.chapter_start, args.chapter_end],
        "target_character_range": [4800, 5600],
        "hard_character_range": [4000, 6800],
        "chapters": list(range(args.chapter_start, args.chapter_end + 1)),
        "chapter_state_plan": contracts,
    }
    output.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
